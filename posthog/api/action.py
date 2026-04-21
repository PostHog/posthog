import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any, cast

from django.db import connection
from django.db.models import Count

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema, extend_schema_field
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action as drf_action
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.event_usage import report_user_action
from posthog.models import Action, Cohort, Insight, Team
from posthog.models.action.action import ACTION_STEP_MATCHING_OPTIONS
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.event.event import Selector
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.property.util import build_selector_regex
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.models.experiment import Experiment

from .documentation import (
    ArrayPropertyFilterSerializer,
    DatePropertyFilterSerializer,
    ExistencePropertyFilterSerializer,
    NumericPropertyFilterSerializer,
    StringPropertyFilterSerializer,
)
from .forbid_destroy_model import ForbidDestroyModel
from .tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin

_PropertyFilterUnion = PolymorphicProxySerializer(
    component_name="ActionStepPropertyFilter",
    serializers=[
        StringPropertyFilterSerializer,
        NumericPropertyFilterSerializer,
        ArrayPropertyFilterSerializer,
        DatePropertyFilterSerializer,
        ExistencePropertyFilterSerializer,
    ],
    resource_type_field_name=None,
)


@extend_schema_field(serializers.ListSerializer(child=_PropertyFilterUnion))
class _ActionStepPropertiesField(serializers.ListField):
    """ListField annotated with a typed OpenAPI schema via a oneOf property filter union.

    Runtime validation remains a simple ListField(child=DictField()) — the
    @extend_schema_field decorator only affects the generated OpenAPI spec.
    """

    pass


class ActionStepJSONSerializer(serializers.Serializer):
    event = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Event name to match (e.g. '$pageview', '$autocapture', or a custom event name).",
    )
    properties = _ActionStepPropertiesField(
        child=serializers.DictField(),
        required=False,
        allow_null=True,
        help_text="Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person).",
    )
    selector = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="CSS selector to match the target element (e.g. 'div > button.cta').",
    )
    selector_regex = serializers.SerializerMethodField()
    tag_name = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text='HTML tag name to match (e.g. "button", "a", "input").',
    )
    text = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Element text content to match.",
    )
    text_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the text value. Defaults to exact.",
    )
    href = serializers.CharField(
        required=False,
        allow_null=True,
        trim_whitespace=False,
        help_text="Link href attribute to match.",
    )
    href_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the href value. Defaults to exact.",
    )
    url = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Page URL to match.",
    )
    url_matching = serializers.ChoiceField(
        choices=ACTION_STEP_MATCHING_OPTIONS,
        required=False,
        allow_null=True,
        help_text="How to match the URL value. Defaults to contains.",
    )

    def get_selector_regex(self, obj) -> str | None:
        selector_str = obj.get("selector") if isinstance(obj, dict) else getattr(obj, "selector", None)
        if not selector_str:
            return None
        try:
            selector = Selector(selector_str, escape_slashes=False)
            return build_selector_regex(selector)
        except Exception:
            return None


class ActionSerializer(
    TaggedItemSerializerMixin, UserAccessControlSerializerMixin, serializers.HyperlinkedModelSerializer
):
    steps = ActionStepJSONSerializer(
        many=True,
        required=False,
        help_text="Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.",
    )
    created_by = UserBasicSerializer(read_only=True)
    is_calculating = serializers.SerializerMethodField()
    is_action = serializers.BooleanField(read_only=True, default=True)
    creation_context = serializers.SerializerMethodField()
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "post_to_slack",
            "slack_message_format",
            "steps",
            "created_at",
            "created_by",
            "deleted",
            "is_calculating",
            "last_calculated_at",
            "team_id",
            "is_action",
            "bytecode_error",
            "pinned_at",
            "creation_context",
            "_create_in_folder",
            "user_access_level",
        ]
        read_only_fields = [
            "team_id",
            "bytecode_error",
        ]
        extra_kwargs = {
            "team_id": {"read_only": True},
            "name": {"help_text": "Name of the action (must be unique within the project)."},
            "description": {"help_text": "Human-readable description of what this action represents."},
            "tags": {"help_text": "Tags for organizing and filtering actions."},
            "post_to_slack": {"help_text": "Whether to post a notification to Slack when this action is triggered."},
            "slack_message_format": {
                "help_text": "Custom Slack message format. Supports templates with event properties."
            },
            "pinned_at": {
                "help_text": "ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin."
            },
        }

    def get_is_calculating(self, action: Action) -> bool:
        return False

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_creation_context(self, obj):
        return None

    def validate(self, attrs):
        instance = cast(Action, self.instance)
        exclude_args = {}
        if instance:
            include_args = {"team": instance.team}
            exclude_args = {"id": instance.pk}
        else:
            attrs["team_id"] = self.context["view"].team_id
            include_args = {"team_id": attrs["team_id"]}
        if attrs.get("pinned_at") == "":
            attrs["pinned_at"] = None

        # Check for empty name - this must come before uniqueness check
        name = attrs.get("name")
        if name is not None and not name.strip():
            raise serializers.ValidationError(
                {"name": "This field may not be blank."},
                code="blank",
            )

        if "name" in attrs:
            colliding_action_ids = list(
                Action.objects.filter(name=attrs["name"], deleted=False, **include_args)
                .exclude(**exclude_args)[:1]
                .values_list("id", flat=True)
            )
            if colliding_action_ids:
                raise serializers.ValidationError(
                    {"name": f"This project already has an action with this name, ID {colliding_action_ids[0]}"},
                    code="unique",
                )

        return attrs

    def create(self, validated_data: Any) -> Any:
        creation_context = self.context["request"].data.get("creation_context")
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)

        report_user_action(
            validated_data["created_by"],
            "action created",
            {**instance.get_analytics_metadata(), "creation_context": creation_context},
            team=instance.team,
            request=self.context["request"],
        )

        return instance

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        if validated_data.get("pinned_at"):
            if instance.pinned_at:
                # drop it from the update
                del validated_data["pinned_at"]
            else:
                # ignore the user-provided timestamp, generate our own
                validated_data["pinned_at"] = datetime.now(UTC).isoformat()

        instance = super().update(instance, validated_data)

        report_user_action(
            self.context["request"].user,
            "action updated",
            {
                **instance.get_analytics_metadata(),
                "updated_by_creator": self.context["request"].user == instance.created_by,
            },
            team=instance.team,
            request=self.context["request"],
        )
        return instance


class ActionReferenceSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Resource type: insight, experiment, cohort, or hog_function")
    id = serializers.CharField(help_text="Resource ID (integer or UUID depending on type)")
    name = serializers.CharField(help_text="Resource name")
    url = serializers.CharField(help_text="Relative URL to the resource")
    created_at = serializers.DateTimeField(help_text="When the resource was created", allow_null=True)
    created_by = UserBasicSerializer(help_text="User who created the resource", allow_null=True)


_ACTION_JSONPATH = (
    '$.** ? ((@.kind == "ActionsNode" && (@.id == $id || @.id == $id_str))'
    " || (@.actionId == $id || @.actionId == $id_str)"
    ' || (@.type == "actions" && (@.id == $id || @.id == $id_str)))'
)
_ACTIONS_ARRAY_JSONPATH = "$.actions[*] ? (@.id == $id || @.id == $id_str)"

_EXPERIMENT_JSON_FIELDS = (
    "metrics",
    "metrics_secondary",
    "filters",
    "parameters",
    "exposure_criteria",
    "stats_config",
    "scheduling_config",
    "variants",
)


def find_action_references(action_id: int, team: Team) -> list[dict[str, Any]]:
    """Find resources that reference a given action using database-level jsonb_path queries."""
    refs: list[dict[str, Any]] = []
    vars_json = json.dumps({"id": action_id, "id_str": str(action_id)})
    cap = 50

    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    insights = (
        Insight.objects.filter(team_id=team.pk, deleted=False)
        .select_related("created_by")
        .extra(
            where=[
                f"""
                jsonb_path_exists(query, '{_ACTION_JSONPATH}', %s::jsonb)
                OR jsonb_path_exists(filters, '{_ACTION_JSONPATH}', %s::jsonb)
                OR jsonb_path_exists(filters, '{_ACTIONS_ARRAY_JSONPATH}', %s::jsonb)
                """
            ],
            params=[vars_json] * 3,
        )
    )
    for insight in insights[:cap]:
        refs.append(
            {
                "type": "insight",
                "id": str(insight.short_id),
                "name": insight.name or insight.derived_name or "Unnamed",
                "url": f"/insights/{insight.short_id}",
                "created_at": insight.created_at,
                "created_by": insight.created_by,
            }
        )

    remaining = cap - len(refs)
    if remaining <= 0:
        return refs

    exp_conditions = []
    for field in _EXPERIMENT_JSON_FIELDS:
        exp_conditions.append(f"jsonb_path_exists({field}, '{_ACTION_JSONPATH}', %s::jsonb)")
        exp_conditions.append(f"jsonb_path_exists({field}, '{_ACTIONS_ARRAY_JSONPATH}', %s::jsonb)")

    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    experiments = (
        Experiment.objects.filter(team_id=team.pk)
        .exclude(deleted=True)
        .select_related("created_by")
        .extra(where=[" OR ".join(exp_conditions)], params=[vars_json] * len(exp_conditions))
    )
    for exp in experiments[:remaining]:
        refs.append(
            {
                "type": "experiment",
                "id": str(exp.id),
                "name": exp.name or "Unnamed",
                "url": f"/experiments/{exp.id}",
                "created_at": exp.created_at,
                "created_by": exp.created_by,
            }
        )

    remaining = cap - len(refs)
    if remaining <= 0:
        return refs

    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    cohorts = (
        Cohort.objects.filter(team__project_id=team.project_id, deleted=False)
        .select_related("created_by")
        .extra(
            where=[
                """
                jsonb_path_exists(filters, '$.** ? (@.event_type == "actions" && (@.key == $id || @.key == $id_str))', %s::jsonb)
                OR jsonb_path_exists(filters, '$.** ? (@.seq_event_type == "actions" && (@.seq_event == $id || @.seq_event == $id_str))', %s::jsonb)
                """
            ],
            params=[vars_json] * 2,
        )
    )
    for cohort in cohorts[:remaining]:
        refs.append(
            {
                "type": "cohort",
                "id": str(cohort.id),
                "name": cohort.name or "Unnamed",
                "url": f"/cohorts/{cohort.id}",
                "created_at": cohort.created_at,
                "created_by": cohort.created_by,
            }
        )

    remaining = cap - len(refs)
    if remaining <= 0:
        return refs

    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    hog_functions = (
        HogFunction.objects.filter(team_id=team.pk, deleted=False)
        .select_related("created_by")
        .extra(
            where=[f"jsonb_path_exists(filters, '{_ACTIONS_ARRAY_JSONPATH}', %s::jsonb)"],
            params=[vars_json],
        )
    )
    for hf in hog_functions[:remaining]:
        refs.append(
            {
                "type": "hog_function",
                "id": str(hf.id),
                "name": hf.name or "Unnamed",
                "url": f"/functions/{hf.id}",
                "created_at": hf.created_at,
                "created_by": hf.created_by,
            }
        )

    return refs


def count_action_references_bulk(action_ids: list[int], team: Team) -> dict[int, int]:
    """Count references for multiple actions in bulk using the same jsonb_path patterns as find_action_references."""
    if not action_ids:
        return {}

    counts: Counter[int] = Counter()
    ids_array = list(action_ids)

    insight_table = Insight._meta.db_table
    cohort_table = Cohort._meta.db_table
    team_table = Team._meta.db_table
    hf_table = HogFunction._meta.db_table

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {insight_table}
                WHERE team_id = %s AND NOT deleted
                AND (
                    jsonb_path_exists(query, '{_ACTION_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
                    OR jsonb_path_exists(filters, '{_ACTION_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
                    OR jsonb_path_exists(filters, '{_ACTIONS_ARRAY_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
                )
            ) AS matched
            GROUP BY aid
            """,
            [ids_array, team.pk],
        )
        for aid, cnt in cursor.fetchall():
            counts[aid] += cnt

    exp_conditions = []
    for field in _EXPERIMENT_JSON_FIELDS:
        exp_conditions.append(
            f"jsonb_path_exists({field}, '{_ACTION_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))"
        )
        exp_conditions.append(
            f"jsonb_path_exists({field}, '{_ACTIONS_ARRAY_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))"
        )
    exp_table = Experiment._meta.db_table
    exp_where = " OR ".join(exp_conditions)

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {exp_table}
                WHERE team_id = %s AND NOT COALESCE(deleted, false)
                AND ({exp_where})
            ) AS matched
            GROUP BY aid
            """,
            [ids_array, team.pk],
        )
        for aid, cnt in cursor.fetchall():
            counts[aid] += cnt

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {cohort_table}
                WHERE team_id IN (SELECT id FROM {team_table} WHERE project_id = %s) AND NOT deleted
                AND (
                    jsonb_path_exists(filters, '$.** ? (@.event_type == "actions" && (@.key == $id || @.key == $id_str))', jsonb_build_object('id', aid, 'id_str', aid::text))
                    OR jsonb_path_exists(filters, '$.** ? (@.seq_event_type == "actions" && (@.seq_event == $id || @.seq_event == $id_str))', jsonb_build_object('id', aid, 'id_str', aid::text))
                )
            ) AS matched
            GROUP BY aid
            """,
            [ids_array, team.project_id],
        )
        for aid, cnt in cursor.fetchall():
            counts[aid] += cnt

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {hf_table}
                WHERE team_id = %s AND NOT deleted
                AND jsonb_path_exists(filters, '{_ACTIONS_ARRAY_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
            ) AS matched
            GROUP BY aid
            """,
            [ids_array, team.pk],
        )
        for aid, cnt in cursor.fetchall():
            counts[aid] += cnt

    return dict(counts)


@extend_schema(tags=[ProductKey.ACTIONS])
class ActionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "action"
    renderer_classes = cast(
        tuple[type[BaseRenderer], ...],
        (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer),
    )
    queryset = Action.objects.select_related("created_by").all()
    serializer_class = ActionSerializer
    ordering = ["-last_calculated_at", "name"]

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))
        return queryset.filter(team_id=self.team_id).order_by(*self.ordering)

    @extend_schema(responses={200: ActionReferenceSerializer(many=True)})
    @drf_action(methods=["GET"], detail=True, required_scopes=["action:read"], pagination_class=None)
    def references(self, request: request.Request, **kwargs: Any) -> Response:
        action_obj = self.get_object()
        refs = find_action_references(action_obj.id, action_obj.team)
        return Response(ActionReferenceSerializer(refs, many=True).data)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        # :HACKY: we need to override this viewset method until actions support
        # better pagination in the taxonomic filter and on the actions page
        actions = self.filter_queryset(self.get_queryset())
        actions_list: list[dict[Any, Any]] = self.serializer_class(
            actions, many=True, context={"request": request, "view": self}
        ).data  # type: ignore

        if request.query_params.get("include_reference_count"):
            action_ids = [a["id"] for a in actions_list]
            ref_counts = count_action_references_bulk(action_ids, self.team)
            for a in actions_list:
                a["reference_count"] = ref_counts.get(a["id"], 0)

        return Response({"results": actions_list})


@mutable_receiver(model_activity_signal, sender=Action)
def handle_action_change(sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs):
    # Detect soft delete/restore by checking the deleted field
    if before_update and after_update:
        if not before_update.deleted and after_update.deleted:
            # Soft deleted
            activity = "deleted"
        elif before_update.deleted and not after_update.deleted:
            # Restored from soft delete
            activity = "updated"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.created_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
        ),
    )
