from typing import cast

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.app_metrics2 import (
    AppMetricResponseSerializer,
    AppMetricsRequestSerializer,
    AppMetricsResponse,
    AppMetricsTotalsResponse,
    AppMetricsTotalsResponseSerializer,
    fetch_app_metric_totals,
    fetch_app_metrics_trends,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.event_filter_config import (
    DEFAULT_FILTER_TREE,
    EventFilterConfig,
    run_test_cases,
    validate_filter_tree,
    validate_test_cases,
)
from posthog.models.team.team import Team
from posthog.utils import relative_date_parse_with_delta_mapping


class EventFilterConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventFilterConfig
        fields = [
            "id",
            "mode",
            "filter_tree",
            "test_cases",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_filter_tree(self, value: object) -> object:
        if value:
            validate_filter_tree(value)
        return value

    def validate_test_cases(self, value: object) -> object:
        if value:
            validate_test_cases(value)
        return value

    def validate(self, attrs: dict) -> dict:
        filter_tree = attrs.get("filter_tree", self.instance.filter_tree if self.instance else None)
        test_cases = attrs.get("test_cases", self.instance.test_cases if self.instance else None)
        if filter_tree and test_cases:
            failures = run_test_cases(filter_tree, test_cases)
            if failures:
                raise ValidationError({"test_cases": failures})
        return attrs


class EventFilterConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Single event filter per team. Auto-creates on first access.
    GET  /event_filter/ — returns the config
    POST /event_filter/ — updates the config (upsert)
    GET  /event_filter/metrics/ — time-series metrics
    GET  /event_filter/metrics/totals/ — aggregate totals
    """

    scope_object = "event_filter"
    scope_object_read_actions = ["list", "retrieve", "metrics", "metrics_totals"]
    scope_object_write_actions = ["create"]
    serializer_class = EventFilterConfigSerializer
    queryset = EventFilterConfig.objects.all()

    def _get_or_create(self) -> EventFilterConfig:
        config, _ = EventFilterConfig.objects.get_or_create(
            team_id=self.team_id,
            defaults={"filter_tree": DEFAULT_FILTER_TREE, "mode": "disabled", "test_cases": []},
        )
        return config

    def list(self, request, **kwargs):
        config = self._get_or_create()
        serializer = self.get_serializer(config)
        return Response(serializer.data)

    def create(self, request, **kwargs):
        config = self._get_or_create()
        serializer = self.get_serializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def _get_config_id(self) -> str | None:
        """Return the config UUID without creating one. Returns None if no config exists."""
        return EventFilterConfig.objects.filter(team_id=self.team_id).values_list("id", flat=True).first()

    def _parse_metrics_params(self, request: Request) -> dict | None:
        """Parse and validate metrics query params. Returns None if no config exists yet."""
        config_id = self._get_config_id()
        if config_id is None:
            return None

        param_serializer = AppMetricsRequestSerializer(data=request.query_params)
        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)
        params = param_serializer.validated_data
        team = cast(Team, self.team)
        after_date, _, _ = relative_date_parse_with_delta_mapping(params.get("after", "-7d"), team.timezone_info)
        before_date, _, _ = relative_date_parse_with_delta_mapping(params.get("before", "-0d"), team.timezone_info)
        return {
            "team_id": self.team_id,
            "app_source": "event_filter",
            "app_source_id": str(config_id),
            "after": after_date,
            "before": before_date,
            "interval": params.get("interval", "day"),
            "breakdown_by": params.get("breakdown_by"),
            "name": params["name"].split(",") if params.get("name") else None,
            "kind": params["kind"].split(",") if params.get("kind") else None,
        }

    @action(detail=False, methods=["GET"], url_path="metrics")
    def metrics(self, request: Request, **kwargs):
        params = self._parse_metrics_params(request)
        if params is None:
            return Response(AppMetricResponseSerializer(instance=AppMetricsResponse(labels=[], series=[])).data)
        data = fetch_app_metrics_trends(**params)
        return Response(AppMetricResponseSerializer(instance=data).data)

    @action(detail=False, methods=["GET"], url_path="metrics/totals")
    def metrics_totals(self, request: Request, **kwargs):
        params = self._parse_metrics_params(request)
        if params is None:
            return Response(AppMetricsTotalsResponseSerializer(instance=AppMetricsTotalsResponse(totals={})).data)
        params.pop("interval", None)
        data = fetch_app_metric_totals(**params)
        return Response(AppMetricsTotalsResponseSerializer(instance=data).data)
