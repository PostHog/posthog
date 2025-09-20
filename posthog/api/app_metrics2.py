from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.utils import action
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team
from posthog.utils import relative_date_parse_with_delta_mapping


@dataclass
class AppMetricSeries:
    name: str
    values: list[int]


@dataclass
class AppMetricsResponse:
    labels: list[str]
    series: list[AppMetricSeries]


class AppMetricResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = AppMetricsResponse


@dataclass
class AppMetricsTotalsResponse:
    totals: dict[str, int]


class AppMetricsTotalsResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = AppMetricsTotalsResponse


class AppMetricsRequestSerializer(serializers.Serializer):
    after = serializers.CharField(required=False, default="-7d")
    before = serializers.CharField(required=False)
    instance_id = serializers.CharField(required=False)
    interval = serializers.ChoiceField(choices=["hour", "day", "week"], required=False, default="day")
    name = serializers.CharField(required=False)
    kind = serializers.CharField(required=False)
    breakdown_by = serializers.ChoiceField(choices=["name", "kind"], required=False, default="kind")


def fetch_app_metrics_trends(
    team_id: int,
    app_source: str,
    app_source_id: str,
    after: datetime,
    before: datetime,
    breakdown_by: str = "kind",
    interval: str = "day",
    instance_id: Optional[str] = None,
    name: Optional[list[str]] = None,
    kind: Optional[list[str]] = None,
) -> AppMetricsResponse:
    """Fetch a list of batch export log entries from ClickHouse."""

    name = name or []
    kind = kind or []

    clickhouse_kwargs: dict[str, Any] = {}

    clickhouse_query = f"""
        SELECT
            toStartOfInterval(timestamp, INTERVAL 1 {interval}) as timestamp,
            metric_{breakdown_by} as breakdown,
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND app_source_id = %(app_source_id)s
        AND timestamp >= toDateTime64(%(after)s, 6)
        AND timestamp <= toDateTime64(%(before)s, 6)
        {'AND instance_id = %(instance_id)s' if instance_id else ''}
        {'AND metric_name IN %(name)s' if name else ''}
        {'AND metric_kind IN %(kind)s' if kind else ''}
        GROUP BY timestamp, breakdown
        ORDER BY timestamp ASC
    """

    clickhouse_kwargs["team_id"] = team_id
    clickhouse_kwargs["app_source"] = app_source
    clickhouse_kwargs["app_source_id"] = app_source_id
    clickhouse_kwargs["after"] = after.strftime("%Y-%m-%dT%H:%M:%S")
    clickhouse_kwargs["before"] = before.strftime("%Y-%m-%dT%H:%M:%S")
    clickhouse_kwargs["instance_id"] = instance_id
    clickhouse_kwargs["name"] = name
    clickhouse_kwargs["kind"] = kind
    clickhouse_kwargs["interval"] = interval.upper()

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    # We create the x values based on the date range and interval
    labels: list[str] = []
    label_format = "%Y-%m-%dT%H:%M" if interval == "hour" else "%Y-%m-%d"

    range_date = after
    # Normalize the start of the range to the start of the interval
    if interval == "hour":
        range_date = range_date.replace(minute=0, second=0, microsecond=0)
    elif interval == "day":
        range_date = range_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif interval == "week":
        range_date = range_date.replace(hour=0, minute=0, second=0, microsecond=0)
        range_date -= timedelta(days=range_date.weekday())

    while range_date <= before:
        labels.append(range_date.strftime(label_format))
        if interval == "hour":
            range_date += timedelta(hours=1)
        elif interval == "day":
            range_date += timedelta(days=1)
        elif interval == "week":
            range_date += timedelta(weeks=1)

    response = AppMetricsResponse(labels=[], series=[])
    data_by_breakdown: dict[str, dict[str, int]] = {}

    breakdown_names = {row[1] for row in results}

    for result in results:
        timestamp, breakdown, count = result
        if breakdown not in data_by_breakdown:
            data_by_breakdown[breakdown] = {}

        data_by_breakdown[breakdown][timestamp.strftime(label_format)] = count

    # Now we can construct the response object

    response.labels = labels

    for breakdown in breakdown_names:
        series = AppMetricSeries(name=breakdown, values=[])
        for x in labels:
            series.values.append(data_by_breakdown.get(breakdown, {}).get(x, 0))
        response.series.append(series)

    return response


def fetch_app_metric_totals(
    team_id: int,
    app_source: str,
    app_source_id: str,
    breakdown_by: str = "kind",
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    instance_id: Optional[str] = None,
    name: Optional[list[str]] = None,
    kind: Optional[list[str]] = None,
) -> AppMetricsTotalsResponse:
    """
    Calculate the totals for the app metrics over the given period.
    """

    name = name or []
    kind = kind or []

    clickhouse_kwargs: dict[str, Any] = {
        "team_id": team_id,
        "app_source": app_source,
        "app_source_id": app_source_id,
        "after": after.strftime("%Y-%m-%dT%H:%M:%S") if after else None,
        "before": before.strftime("%Y-%m-%dT%H:%M:%S") if before else None,
    }

    clickhouse_query = f"""
        SELECT
            metric_{breakdown_by} as breakdown,
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND app_source_id = %(app_source_id)s
        {'AND timestamp >= toDateTime64(%(after)s, 6)' if after else ''}
        {'AND timestamp <= toDateTime64(%(before)s, 6)' if before else ''}
        {'AND instance_id = %(instance_id)s' if instance_id else ''}
        {'AND metric_name IN %(name)s' if name else ''}
        {'AND metric_kind IN %(kind)s' if kind else ''}
        GROUP BY breakdown
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals = {row[0]: row[1] for row in results}
    return AppMetricsTotalsResponse(totals=totals)


class AppMetricsMixin(viewsets.GenericViewSet):
    app_source: str  # Should be set by the inheriting class

    def get_app_metrics_instance_id(self) -> Optional[str]:
        """
        Can be used overridden to help with getting the instance_id for the app metrics.
        Otherwise it defaults to null or the query param if given
        """
        raise NotImplementedError()

    @action(detail=True, methods=["GET"])
    def metrics(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        param_serializer = AppMetricsRequestSerializer(data=request.query_params)

        if not self.app_source:
            raise ValidationError("app_source not set on the viewset")

        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)

        params = param_serializer.validated_data

        try:
            instance_id = self.get_app_metrics_instance_id()
        except NotImplementedError:
            instance_id = params.get("instance_id")

        team = cast(Team, self.team)  # type: ignore

        after_date, _, _ = relative_date_parse_with_delta_mapping(params.get("after", "-7d"), team.timezone_info)
        before_date, _, _ = relative_date_parse_with_delta_mapping(params.get("before", "-0d"), team.timezone_info)

        data = fetch_app_metrics_trends(
            team_id=self.team_id,  # type: ignore
            app_source=self.app_source,
            app_source_id=str(obj.id),
            # From request params
            instance_id=instance_id,
            interval=params.get("interval", "day"),
            after=after_date,
            before=before_date,
            breakdown_by=params.get("breakdown_by"),
            name=params["name"].split(",") if params.get("name") else None,
            kind=params["kind"].split(",") if params.get("kind") else None,
        )

        serializer = AppMetricResponseSerializer(instance=data)
        return Response(serializer.data)

    @action(detail=True, methods=["GET"], url_path="metrics/totals")
    def metrics_totals(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        param_serializer = AppMetricsRequestSerializer(data=request.query_params)

        if not self.app_source:
            raise ValidationError("app_source not set on the viewset")

        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)

        params = param_serializer.validated_data
        team = cast(Team, self.team)  # type: ignore

        after_date = None
        before_date = None

        if params.get("after"):
            after_date, _, _ = relative_date_parse_with_delta_mapping(params["after"], team.timezone_info)

        if params.get("before"):
            before_date, _, _ = relative_date_parse_with_delta_mapping(params["before"], team.timezone_info)

        data = fetch_app_metric_totals(
            team_id=self.team_id,  # type: ignore
            app_source=self.app_source,
            app_source_id=str(obj.id),
            # From request params
            after=after_date,
            before=before_date,
            breakdown_by=params.get("breakdown_by"),
            name=params["name"].split(",") if params.get("name") else None,
            kind=params["kind"].split(",") if params.get("kind") else None,
        )

        serializer = AppMetricsTotalsResponseSerializer(instance=data)
        return Response(serializer.data)
