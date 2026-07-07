from datetime import datetime
from typing import Any

from django.db.models import Prefetch, Q, QuerySet

from rest_framework import filters, pagination, serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models import TaggedItem

from products.annotations.backend.models.annotation import Annotation
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.models.insight import Insight


class AnnotationSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    dashboard_id = serializers.IntegerField(required=False, allow_null=True)
    dashboard_item = TeamScopedPrimaryKeyRelatedField(queryset=Insight.objects.all(), required=False, allow_null=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        max_length=100,
        help_text=(
            "Tag names this annotation is scoped to. When `scope` is `tag`, the annotation is shown on every "
            "dashboard and insight carrying one of these tags. Required (non-empty) when `scope` is `tag`, "
            "and only allowed with that scope."
        ),
    )

    class Meta:
        model = Annotation
        fields = [
            "id",
            "content",
            "date_marker",
            "creation_type",
            "dashboard_item",
            "dashboard_id",
            "dashboard_name",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "scope",
            "emoji",
            "hidden_in_user_interface",
            "tags",
        ]
        read_only_fields = [
            "id",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "dashboard_name",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "content": {
                "help_text": "Annotation text shown on charts to describe the change, release, or incident.",
            },
            "date_marker": {
                "help_text": "When this annotation happened (ISO 8601 timestamp). Used to position it on charts.",
            },
            "creation_type": {
                "help_text": "Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.",
            },
            "dashboard_id": {
                "help_text": "Optional dashboard ID to attach this annotation to. Must belong to the current project.",
            },
            "dashboard_item": {
                "help_text": "Optional insight ID to attach this annotation to. Must belong to the current project.",
            },
            "deleted": {
                "help_text": "Soft-delete flag. Set to true to hide the annotation, or false to restore it.",
            },
            "scope": {
                "help_text": (
                    "Annotation visibility scope: `project`, `organization`, `dashboard`, `dashboard_item`, or "
                    "`tag`. With `tag`, the annotation shows on every dashboard and insight carrying one of the "
                    "annotation's `tags`. `recording` is deprecated and rejected."
                ),
            },
            "emoji": {
                "help_text": "Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.",
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
            "hidden_in_user_interface": {
                "help_text": (
                    "When true, the annotation is hidden from the PostHog UI (charts and the annotations list) "
                    "but still readable over the API and MCP. Use for high-frequency markers like deployments "
                    "that would otherwise crowd the UI. Null (the default) means the annotation is shown."
                ),
                "required": False,
                "allow_null": True,
            },
        }

    def validate_emoji(self, value: str | None) -> str | None:
        # Normalise blank strings to None so the DB has a single canonical "no emoji" state.
        return value or None

    def update(self, instance: Annotation, validated_data: dict[str, Any]) -> Annotation:
        instance.team_id = self.context["team_id"]
        # `tags` isn't a model field; TaggedItemSerializerMixin.update persists it from initial_data.
        validated_data.pop("tags", None)
        return super().update(instance, validated_data)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self.context["get_team"]()

        dashboard_id = attrs.get("dashboard_id")
        if dashboard_id is not None:
            if not Dashboard.objects.filter(id=dashboard_id, team_id=team.id).exists():
                raise serializers.ValidationError({"dashboard_id": "Dashboard not found."})

        scope = attrs.get("scope", None)
        if scope == Annotation.Scope.RECORDING.value:
            raise serializers.ValidationError("Recording scope is deprecated")

        # A tag-scoped annotation with no tags would match no surface, so require at least one.
        # Conversely, tags define where a tag-scoped annotation shows, so they're meaningless on other scopes.
        effective_scope = attrs.get("scope") if "scope" in attrs else (self.instance.scope if self.instance else None)
        if effective_scope == Annotation.Scope.TAG.value:
            if "tags" in attrs:
                tags = attrs.get("tags")
            elif self.instance is not None:
                tags = list(self.instance.tagged_items.values_list("tag__name", flat=True))
            else:
                tags = None
            if not tags:
                raise serializers.ValidationError({"tags": "At least one tag is required when scope is 'tag'."})
        elif attrs.get("tags"):
            raise serializers.ValidationError({"tags": "Tags can only be set when scope is 'tag'."})

        return attrs

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> Annotation:
        request = self.context["request"]
        team = self.context["get_team"]()

        tags = validated_data.pop("tags", None)
        annotation = Annotation.objects.create(
            organization_id=team.organization_id,
            team_id=team.id,
            created_by=request.user,
            **validated_data,
        )
        self._attempt_set_tags(tags, annotation)
        return annotation


class AnnotationsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 1000


class AnnotationsViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
    """

    scope_object = "annotation"
    queryset = (
        Annotation.objects.select_related("dashboard_item")
        .select_related("created_by")
        .prefetch_related(
            Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
        )
    )
    serializer_class = AnnotationSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = AnnotationsLimitOffsetPagination
    search_fields = ["content"]

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-date_marker")
        if self.action != "partial_update":
            # We never want deleted items to be included in the queryset… except when we want to restore an annotation
            # That's because annotations are restored with a PATCH request setting `deleted` to `False`
            queryset = queryset.filter(deleted=False)
        # Annotations attached to a soft-deleted insight or dashboard are hidden
        # across all actions — including `partial_update`, so they cannot be
        # individually edited or restored while their parent is soft-deleted.
        # They reappear automatically when the parent is restored. Mirrors how
        # alerts behave (see posthog/temporal/alerts/activities.py).
        queryset = queryset.filter(
            Q(dashboard_item__isnull=True) | Q(dashboard_item__deleted=False),
            Q(dashboard__isnull=True) | Q(dashboard__deleted=False),
        )

        scope = self.request.query_params.get("scope")
        if scope:
            # let's allow the more recently used "insight" scope to be used as "dashboard_item"
            scope = "dashboard_item" if scope == "insight" else scope
            if scope not in [scope.value for scope in Annotation.Scope]:
                raise serializers.ValidationError(f"Invalid scope: {scope}")

            queryset = queryset.filter(scope=scope)

        # Add date range filtering
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        date_from_parsed = None
        date_to_parsed = None

        if date_from:
            try:
                date_from_parsed = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__gte=date_from_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_from must be a valid ISO 8601 date")

        if date_to:
            try:
                date_to_parsed = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__lte=date_to_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_to must be a valid ISO 8601 date")

        if date_from_parsed and date_to_parsed and date_from_parsed > date_to_parsed:
            raise serializers.ValidationError("Invalid date range: date_from must be before date_to")

        # Add is_emoji filtering
        is_emoji = self.request.query_params.get("is_emoji")
        if is_emoji is not None:
            # Convert string to boolean (true, 1, yes -> True; false, 0, no -> False)
            is_emoji_bool = is_emoji.lower() in ("true", "1", "yes")
            queryset = queryset.filter(is_emoji=is_emoji_bool)

        hidden_in_user_interface = self.request.query_params.get("hidden_in_user_interface")
        if hidden_in_user_interface is not None:
            if hidden_in_user_interface.lower() in ("true", "1", "yes"):
                queryset = queryset.filter(hidden_in_user_interface=True)
            else:
                queryset = queryset.filter(Q(hidden_in_user_interface=False) | Q(hidden_in_user_interface__isnull=True))

        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        team = self.team
        return queryset.filter(
            Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id) | Q(team=team)
        )
