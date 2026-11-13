import json
from dataclasses import asdict
from functools import lru_cache
from typing import Any, Optional, cast

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_field,
    extend_schema_serializer,
)
from rest_framework import request, serializers, status, viewsets
from rest_framework.decorators import action as drf_action
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.hogql.errors import QueryError
from posthog.hogql.property import validate_regex

from posthog.api.documentation import (
    ArrayPropertyFilterSerializer,
    DatePropertyFilterSerializer,
    ExistencePropertyFilterSerializer,
    NumericPropertyFilterSerializer,
    StringPropertyFilterSerializer,
)
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.property_filter_access_gate import table_blocking_property_filters
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import (
    BULK_UPDATE_TAGS_SKIPPED_REASON,
    BulkUpdateTagsRequestSerializer,
    BulkUpdateTagsResponseSerializer,
    TaggedItemViewSetMixin,
)
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.models.event.event import MAX_SELECTOR_LENGTH, Selector, SelectorTooLongError
from posthog.models.property.util import build_selector_regex
from posthog.permissions import is_service_auth
from posthog.resource_limits import LimitKey, check_count_limit
from posthog.taxonomy.hidden_events import HIDDEN_EVENT_REASON, added_hidden_event

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)
from products.actions.backend.facade import api, contracts
from products.actions.backend.facade.contracts import (
    ACTION_ORDERING_FIELDS,
    ACTION_STEP_MATCHING_OPTIONS,
    ActionOrderingField,
    ActionWriteField,
)
from products.feature_flags.backend.facade.flags import hides_flag_calls_from_query_builders

logger = structlog.get_logger(__name__)

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


# An entry holds the selector plus its compiled regex, which is larger, for the life of
# the process. Nobody hand-writes a CSS selector this long, so cap what gets retained.
_MAX_CACHED_SELECTOR_LENGTH = 1_000


@frozen
class _CompiledSelector:
    regex: str | None
    warning: str | None


def _compile_selector_uncached(selector_str: str) -> _CompiledSelector:
    try:
        selector = Selector(selector_str, escape_slashes=False)
        warning = None
        if selector.has_unsupported_syntax():
            warning = "This selector uses CSS we cannot match on. Try matching on the element tag, id, or class."
        return _CompiledSelector(regex=build_selector_regex(selector), warning=warning)
    except Exception:
        logger.exception("Failed to compile action selector")
        return _CompiledSelector(
            regex=None,
            warning="This selector could not be read, so it will not match any events. Check that it is valid CSS.",
        )


@lru_cache(maxsize=2048)
def _compile_selector_cached(selector_str: str) -> _CompiledSelector:
    return _compile_selector_uncached(selector_str)


def _compile_selector(selector_str: str) -> _CompiledSelector:
    # Cached because the selector_regex and selector_warning fields both need it for
    # every serialized action step. An outsized or non-string selector skips the cache:
    # lru_cache hashes its argument before the body runs, so an unhashable one would
    # raise from the lookup itself.
    if not isinstance(selector_str, str) or len(selector_str) > _MAX_CACHED_SELECTOR_LENGTH:
        return _compile_selector_uncached(selector_str)
    return _compile_selector_cached(selector_str)


def _selector_str(obj) -> str | None:
    return obj.get("selector") if isinstance(obj, dict) else getattr(obj, "selector", None)


def _action_access_ref(action: contracts.Action | contracts.ActionDetail, team_id: int) -> ObjectAccessRef:
    # The request's team, so a project's environment checks the action against its own access rules.
    return ObjectAccessRef(resource="action", id=str(action.id), team_id=team_id, created_by_id=action.created_by_id)


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
    selector_regex = serializers.SerializerMethodField(
        help_text="Compiled regex the selector matches against the event elements chain. Null when no selector is set."
    )
    selector_warning = serializers.SerializerMethodField(
        help_text="Set when the selector compiles to a matcher that cannot match any event. Null when the selector is valid or absent."
    )
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
        selector_str = _selector_str(obj)
        return _compile_selector(selector_str).regex if selector_str else None

    def get_selector_warning(self, obj) -> str | None:
        selector_str = _selector_str(obj)
        return _compile_selector(selector_str).warning if selector_str else None


# drf-spectacular publishes this docstring in the Action schema, so changing it changes the published API.
class ActionSerializer(UserAccessControlSerializerMixin, serializers.Serializer):
    """Serializer mixin that handles tags for objects."""

    id = serializers.IntegerField(read_only=True, label="ID")
    name = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        max_length=400,
        required=False,
        help_text="Name of the action (must be unique within the project).",
    )
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        style={"base_template": "textarea.html"},
        help_text="Human-readable description of what this action represents.",
    )
    # No help_text, because a description would change the published schema of the field.
    tags = serializers.ListField(required=False)
    post_to_slack = serializers.BooleanField(
        required=False,
        help_text="Whether to post a notification to Slack when this action is triggered.",
    )
    slack_message_format = serializers.CharField(
        allow_blank=True,
        max_length=1200,
        required=False,
        help_text="Custom Slack message format. Supports templates with event properties.",
    )
    steps = ActionStepJSONSerializer(
        many=True,
        required=False,
        help_text="Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    deleted = serializers.BooleanField(required=False)
    is_calculating = serializers.SerializerMethodField()
    last_calculated_at = serializers.DateTimeField(required=False)
    team_id = serializers.IntegerField(read_only=True)
    is_action = serializers.BooleanField(read_only=True, default=True)
    bytecode_error = serializers.CharField(read_only=True, allow_null=True)
    pinned_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.",
    )
    creation_context = serializers.SerializerMethodField()
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    user_access_level = serializers.SerializerMethodField(
        method_name="get_action_access_level",
        read_only=True,
        help_text="The effective access level the user has for this object",
    )

    # A plain serializer ignores Meta; `get_fields` orders by it and surveys projects stored actions with it.
    class Meta:
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

    def get_fields(self) -> dict[str, serializers.Field]:
        # DRF puts base-class fields such as `user_access_level` first; the published schema uses Meta's order.
        fields = super().get_fields()
        return {name: fields[name] for name in self.Meta.fields}

    def get_is_calculating(self, action: contracts.ActionDetail) -> bool:
        return False

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_creation_context(self, obj) -> None:
        return None

    def get_action_access_level(self, action: contracts.ActionDetail) -> Optional[str]:
        if self.user_access_control is None:
            return None
        return self.get_user_access_level(_action_access_ref(action, team_id=self.context["get_team"]().id))

    def validate_steps(self, steps: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        # ClickHouse compiles these with RE2 at query time, so one pattern RE2 rejects fails
        # every insight that uses the action. steps_to_expr runs this same check on stored steps.
        # These checks run here and not on the step serializer because the error renderer turns an
        # error nested inside one list item into a Python repr instead of a readable message.
        for step in steps or []:
            selector = step.get("selector")
            if isinstance(selector, str) and len(selector) > MAX_SELECTOR_LENGTH:
                raise serializers.ValidationError(str(SelectorTooLongError(len(selector))), code="max_length")
            for value_field, matching_field in (
                ("url", "url_matching"),
                ("href", "href_matching"),
                ("text", "text_matching"),
            ):
                value = step.get(value_field)
                if step.get(matching_field) != "regex" or not isinstance(value, str):
                    continue
                try:
                    validate_regex(value)
                except QueryError as err:
                    raise serializers.ValidationError(str(err)) from err
        return steps

    def validate(self, attrs):
        instance = cast(contracts.ActionDetail | None, self.instance)
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
            colliding_action_id = api.find_action_id_by_name(
                team_id=instance.team_id if instance else self.context["view"].team_id,
                name=attrs["name"],
                exclude_action_id=instance.id if instance else None,
            )
            if colliding_action_id is not None:
                raise serializers.ValidationError(
                    {"name": f"This project already has an action with this name, ID {colliding_action_id}"},
                    code="unique",
                )

        if "steps" in attrs:
            step_filters = [prop for step in attrs["steps"] for prop in (step.get("properties") or [])]
            denied_table = table_blocking_property_filters(
                self.context["request"].user, self.context["get_team"](), step_filters
            )
            if denied_table:
                raise serializers.ValidationError(
                    {"steps": f"This filter uses the table '{denied_table}', which you don't have access to."},
                    code="permission_denied",
                )
            hidden_event = added_hidden_event(
                (step.get("event") for step in attrs["steps"]),
                instance.get_step_events() if instance else [],
            )
            if hidden_event and hides_flag_calls_from_query_builders(self.context["get_team"]().organization_id):
                raise serializers.ValidationError(
                    {"steps": f"You can't add a new step on {hidden_event}. {HIDDEN_EVENT_REASON}"},
                    code="hidden_event",
                )

        return attrs

    def to_write(self) -> contracts.ActionWrite:
        values: dict[str, Any] = {}
        fields_set: set[ActionWriteField] = set()
        for name, value in self.validated_data.items():
            if name == "steps":
                values["steps"] = tuple(contracts.ActionStep(**step) for step in value)
                fields_set.add(ActionWriteField.STEPS)
            elif name == "tags":
                values["tags"] = tuple(value)
                fields_set.add(ActionWriteField.TAGS)
            elif name == "_create_in_folder":
                values["create_in_folder"] = value
                fields_set.add(ActionWriteField.CREATE_IN_FOLDER)
            else:
                values[name] = value
                fields_set.add(ActionWriteField(name))
        return contracts.ActionWrite(fields_set=frozenset(fields_set), **values)


class ActionReferenceSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Resource type: insight, experiment, cohort, or hog_function")
    id = serializers.CharField(help_text="Resource ID (integer or UUID depending on type)")
    name = serializers.CharField(help_text="Resource name")
    url = serializers.CharField(help_text="Relative URL to the resource")
    created_at = serializers.DateTimeField(help_text="When the resource was created", allow_null=True)
    created_by = UserBasicSerializer(help_text="User who created the resource", allow_null=True)


class ActionListPagingQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, min_value=0, help_text="Maximum number of actions to return. Omit to return all."
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="Number of actions to skip before returning results."
    )


@extend_schema_serializer(many=False)
class ActionListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(
        help_text="Number of actions that match the filters. Without `limit`, it is `offset` plus the number of actions returned."
    )
    results = ActionSerializer(many=True, help_text="Actions on this page, or every matching action without `limit`.")


class ActionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    ForbidDestroyModel,
    viewsets.GenericViewSet,
):
    scope_object = "action"
    path_parameters = {
        "pk": PathParameter(type=int, description="A unique integer value identifying this action."),
    }
    renderer_classes = cast(
        tuple[type[BaseRenderer], ...],
        (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer),
    )
    serializer_class = ActionSerializer

    def read_object(self) -> contracts.ActionDetail | None:
        try:
            return api.get_action_detail(team_id=self.team_id, action_id=self.kwargs["pk"])
        except contracts.ActionNotFound:
            return None

    def object_access_ref(self, record: contracts.Action | contracts.ActionDetail) -> ObjectAccessRef:
        return _action_access_ref(record, team_id=self.team.id)

    def _list_access(self) -> contracts.ActionListAccess | None:
        """The access control narrowing a queryset list gets from TeamAndOrgViewSetMixin, with the same gates."""
        if is_service_auth(self.request):
            return None
        access = self.user_access_control.list_access_filter(
            "action", include_all_if_admin=self.request.GET.get("admin_include_all") == "true"
        )
        if access is None:
            return None
        return contracts.ActionListAccess(
            viewer_id=cast(User, self.request.user).id,
            only_allowed=access.only_allowed,
            allowed_ids=access.allowed_ids,
            blocked_ids=access.blocked_ids,
        )

    @staticmethod
    def _ordering_from_request(request: request.Request) -> contracts.ActionOrdering | None:
        raw = request.query_params.get("ordering")
        if not raw:
            return None
        field = raw.lstrip("-")
        if field not in ACTION_ORDERING_FIELDS:
            return None
        return contracts.ActionOrdering(field=cast(ActionOrderingField, field), descending=raw.startswith("-"))

    def _list_filters(self, request: request.Request) -> contracts.ActionListFilters:
        created_by = request.query_params.get("created_by")
        creator_ids = tuple(int(v) for v in created_by.split(",") if v.strip().isdigit()) if created_by else ()

        tags_list: Any = None
        tags = request.query_params.get("tags")
        if tags:
            try:
                tags_list = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags_list = None

        return contracts.ActionListFilters(
            search=request.query_params.get("search") or None,
            created_by_ids=creator_ids,
            tags=tuple(tags_list) if tags_list else (),
            ordering=self._ordering_from_request(request),
        )

    @extend_schema(responses={200: ActionReferenceSerializer(many=True)})
    @drf_action(methods=["GET"], detail=True, required_scopes=["action:read"], pagination_class=None)
    def references(self, request: request.Request, **kwargs: Any) -> Response:
        action_obj = self.get_object()
        refs = api.find_action_references(
            team_id=action_obj.team_id, project_id=self.team.project_id, action_id=action_obj.id
        )
        return Response(ActionReferenceSerializer(refs, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "limit", OpenApiTypes.INT, description="Maximum number of actions to return. Omit to return all."
            ),
            OpenApiParameter(
                "offset", OpenApiTypes.INT, description="Number of actions to skip before returning results."
            ),
            OpenApiParameter(
                "search", OpenApiTypes.STR, description="Case-insensitive substring match on the action name."
            ),
            OpenApiParameter(
                "created_by",
                OpenApiTypes.STR,
                description="Comma-separated list of creator user ids. Returns only actions created by these users.",
            ),
            OpenApiParameter(
                "tags",
                OpenApiTypes.STR,
                description='JSON-encoded array of tag names, e.g. ["billing","beta"]. Returns actions having any of these tags.',
            ),
            OpenApiParameter(
                "ordering",
                OpenApiTypes.STR,
                description="Field to order by (name, created_at, pinned_at, created_by). Prefix with '-' for descending.",
            ),
        ],
        responses={200: ActionListResponseSerializer(many=False)},
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        # :HACKY: we need to override this viewset method until actions support
        # better pagination in the taxonomic filter and on the actions page.
        #
        # `limit`/`offset`/`search`/`created_by`/`tags`/`ordering` are opt-in: with
        # no params we still return the full, ordered list so the taxonomic filter
        # and other in-memory consumers of the shared actions list keep working
        # unchanged. The actions page and API/MCP consumers pass them to avoid
        # pulling every action at once (a project can have thousands), which
        # otherwise overflows the context window of LLM clients calling the
        # `actions-get-all` MCP tool.
        filters = self._list_filters(request)
        access = self._list_access()

        paging = ActionListPagingQuerySerializer(data=request.query_params)
        paging.is_valid(raise_exception=True)

        page = api.list_action_details(
            team_id=self.team_id,
            filters=filters,
            access=access,
            offset=paging.validated_data["offset"],
            limit=paging.validated_data.get("limit"),
        )
        actions_list: list[dict[Any, Any]] = self.get_serializer(page.results, many=True).data

        if request.query_params.get("include_reference_count"):
            ref_counts = api.count_action_references(
                team_id=self.team.id,
                project_id=self.team.project_id,
                action_ids=[a["id"] for a in actions_list],
            )
            for a in actions_list:
                a["reference_count"] = ref_counts.get(a["id"], 0)

        return Response({"count": page.count, "results": actions_list})

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ActionSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        check_count_limit(
            team=self.team,
            key=LimitKey.MAX_ACTIONS_PER_TEAM,
            current_count=api.count_live_actions(team_id=self.team.id),
            user=user,
        )
        result = api.add_action(team_id=self.team_id, created_by=user, write=serializer.to_write())

        report_user_action(
            user,
            "action created",
            {**asdict(result.analytics), "creation_context": request.data.get("creation_context")},
            team=self.team,
            request=request,
        )
        return Response(self.get_serializer(result.action).data, status=status.HTTP_201_CREATED)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=False)

    def partial_update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: request.Request, *, partial: bool) -> Response:
        action = self.get_object()
        serializer = ActionSerializer(action, data=request.data, partial=partial, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        result = api.edit_action(team_id=self.team_id, action_id=action.id, write=serializer.to_write())

        user = cast(User, request.user)
        report_user_action(
            user,
            "action updated",
            {
                **asdict(result.analytics),
                "updated_by_creator": result.action.created_by_id is not None
                and result.action.created_by_id == user.id,
            },
            team=self.team,
            request=request,
        )
        return Response(self.get_serializer(result.action).data)

    @extend_schema(
        request=BulkUpdateTagsRequestSerializer,
        responses={200: BulkUpdateTagsResponseSerializer},
    )
    @drf_action(methods=["POST"], detail=False)
    def bulk_update_tags(self, request: request.Request, **kwargs: Any) -> Response:
        serializer = BulkUpdateTagsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_ids: list[int] = serializer.validated_data["ids"]

        editable_ids: list[int] = []
        skipped: list[dict[str, Any]] = []
        actions = api.list_actions_in_list_order(team_id=self.team_id, action_ids=action_ids)
        for action in actions:
            access_level = self.user_access_control.access_level_for_ref(self.object_access_ref(action))
            if access_level and access_level_satisfied_for_resource("action", access_level, "editor"):
                editable_ids.append(action.id)
            else:
                skipped.append({"id": action.id, "reason": BULK_UPDATE_TAGS_SKIPPED_REASON})

        found_ids = {action.id for action in actions}
        skipped += [
            {"id": action_id, "reason": BULK_UPDATE_TAGS_SKIPPED_REASON}
            for action_id in action_ids
            if action_id not in found_ids
        ]

        changes = api.change_action_tags(
            team_id=self.team_id,
            action_ids=editable_ids,
            tag_action=serializer.validated_data["action"],
            tags=serializer.validated_data["tags"],
        )
        return Response(
            BulkUpdateTagsResponseSerializer(
                {"updated": [{"id": change.id, "tags": list(change.tags)} for change in changes], "skipped": skipped}
            ).data
        )

    # Shared so this endpoint is documented like every TaggedItemViewSetMixin bulk tag endpoint.
    bulk_update_tags.__doc__ = TaggedItemViewSetMixin.bulk_update_tags.__doc__
