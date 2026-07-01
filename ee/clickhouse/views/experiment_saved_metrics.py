from django.db.models import QuerySet
from django.db.models.functions import Lower

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.metric_utils import filter_metric_group_ids_by_event, refresh_action_names_in_metric
from products.experiments.backend.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric

from ee.api.rbac.access_control import AccessControlViewSetMixin


class ExperimentToSavedMetricSerializer(serializers.ModelSerializer):
    query = serializers.JSONField(source="saved_metric.query", read_only=True)
    name = serializers.CharField(source="saved_metric.name", read_only=True)

    class Meta:
        model = ExperimentToSavedMetric
        fields = [
            "id",
            "experiment",
            "saved_metric",
            "metadata",
            "created_at",
            "query",
            "name",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def to_representation(self, instance: ExperimentToSavedMetric):
        data = super().to_representation(instance)
        # Refresh action names to show current names instead of stale cached values.
        # actions_by_id is preloaded once per page by ExperimentListSerializer (shared via the
        # parent serializer context); None when used standalone, falling back to a per-call query.
        team = instance.experiment.team
        actions_by_id = self.context.get("actions_by_id")
        data["query"] = refresh_action_names_in_metric(data.get("query"), team, actions_by_id)
        return data


class ExperimentSavedMetricSerializer(
    UserAccessControlSerializerMixin, TaggedItemSerializerMixin, serializers.ModelSerializer
):
    created_by = UserBasicSerializer(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Name of the shared metric. Must be unique within the project (case-insensitive).",
    )
    description = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Short description of what the metric measures.",
    )
    query = serializers.JSONField(
        help_text=(
            "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: "
            "'mean' (set source to an EventsNode with an event name), "
            "'funnel' (set series to an array of EventsNode steps), "
            "'ratio' (set numerator and denominator EventsNode entries), or "
            "'retention' (set start_event and completion_event). "
            "Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
        ),
    )

    class Meta:
        model = ExperimentSavedMetric
        fields = [
            "id",
            "name",
            "description",
            "query",
            "created_by",
            "created_at",
            "updated_at",
            "tags",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
        ]

    def validate_name(self, value: str) -> str:
        team = self.context["get_team"]()
        qs = ExperimentSavedMetric.objects.filter(team=team, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A shared metric with this name already exists.")
        return value

    def to_representation(self, instance: ExperimentSavedMetric):
        data = super().to_representation(instance)
        # Refresh action names to show current names instead of stale cached values
        team = self.context["get_team"]()
        data["query"] = refresh_action_names_in_metric(data.get("query"), team)
        return data

    def create(self, validated_data):
        tags = validated_data.pop("tags", None)
        name = validated_data.pop("name")
        query = validated_data.pop("query")
        description = validated_data.pop("description", None)

        if validated_data:
            raise serializers.ValidationError(
                f"Can't create keys: {', '.join(sorted(validated_data))} on ExperimentSavedMetric"
            )

        service = self._build_service()
        instance = service.create_saved_metric(name=name, query=query, description=description)
        self._attempt_set_tags(tags, instance)
        return instance

    def update(self, instance: ExperimentSavedMetric, validated_data):
        tags = validated_data.pop("tags", None)
        service = self._build_service()
        instance = service.update_saved_metric(instance, validated_data)
        self._attempt_set_tags(tags, instance)
        return instance

    def _build_service(self) -> ExperimentSavedMetricService:
        request = self.context["request"]
        return ExperimentSavedMetricService(team=self.context["get_team"](), user=request.user)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="event",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter to shared metrics whose query references this event name. Matches events "
                "used directly in metric queries as well as events behind any actions those metrics reference. "
                "Use this for reuse discovery (find a metric by what it measures); distinct from 'search', "
                "which matches the metric's own name/description/tags.",
            ),
        ],
    ),
)
@extend_schema(extensions={"x-swagger-tag": "experiment_saved_metrics", "x-product": "experiments"})
class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment_saved_metric"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").order_by(Lower("name")).distinct()
    serializer_class = ExperimentSavedMetricSerializer
    filter_backends = [filters.SearchFilter]
    # `search` matches the metric's own name/description/tags, while `event` looks in metrics
    search_fields = ["name", "description", "tagged_items__tag__name"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # `?event=` matches metrics whose query references the event directly (EventsNode) or via an action's
        # step events (ActionsNode resolved live) — mirrors the experiments-list filter. Scoped to `list` so it
        # never narrows a detail/update/destroy lookup. Rows are read team-scoped (safely_get_queryset runs
        # before the mixin's team filter), then matched in Python since event references live deep in the JSON.
        if self.action != "list":
            return queryset
        event = self.request.query_params.get("event")
        if event:
            # One group per saved metric: (pk, [its query]). `.order_by()` drops the class-level
            # ordering for this internal fetch — the result is matched in Python, so ordering is
            # irrelevant, and it avoids a needless sort (and the DISTINCT+ORDER BY column injection).
            groups = [
                (pk, [query] if query else [])
                for pk, query in queryset.filter(team_id=self.team.pk).order_by().values_list("pk", "query")
            ]
            queryset = queryset.filter(pk__in=filter_metric_group_ids_by_event(groups, event, self.team))
        return queryset

    def perform_destroy(self, instance: ExperimentSavedMetric) -> None:
        service = ExperimentSavedMetricService(team=self.team, user=self.request.user)
        service.delete_saved_metric(instance)
