from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.utils import action
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.schema_enums import ProductKey
from posthog.utils import relative_date_parse_with_delta_mapping

APP_SOURCE_TO_PRODUCT_KEY: dict[str, ProductKey] = {
    "hog_function": ProductKey.PIPELINE_DESTINATIONS,
    "hog_flow": ProductKey.WORKFLOWS,
    "batch_export": ProductKey.PIPELINE_BATCH_EXPORTS,
}


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


@frozen
class MetricSeries:
    """Which app-metric rows a read covers. Both fields are strings, so naming them keeps a caller
    from passing the id where the source goes."""

    app_source: str
    app_source_id: str


# Every hog flow metric is mirrored under this app source with the version appended to the flow id,
# which is what makes a per-version read possible. Written by the CDP worker's monitoring service.
HOG_FLOW_VERSION_APP_SOURCE = "hog_flow_version"


class AppMetricsRequestSerializer(serializers.Serializer):
    after = serializers.CharField(
        required=False,
        default="-7d",
        help_text="Start of the time range. Accepts relative formats like '-7d', '-24h' or ISO 8601 timestamps. Defaults to '-7d'.",
    )
    before = serializers.CharField(
        required=False,
        help_text="End of the time range. Same format as 'after'. Defaults to now.",
    )
    instance_id = serializers.CharField(
        required=False,
        help_text="Filter metrics to a specific execution instance.",
    )
    interval = serializers.ChoiceField(
        choices=["hour", "day", "week"],
        required=False,
        default="day",
        help_text="Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.",
    )
    name = serializers.CharField(
        required=False,
        help_text="Comma-separated metric names to filter by.",
    )
    kind = serializers.CharField(
        required=False,
        help_text="Comma-separated metric kinds to filter by, e.g. 'success,failure'.",
    )
    breakdown_by = serializers.ChoiceField(
        choices=["name", "kind"],
        required=False,
        default="kind",
        help_text="Group the series by metric 'name' or 'kind'. Defaults to 'kind'.",
    )
    version = serializers.IntegerField(
        required=False,
        help_text=(
            "Read one workflow version's metrics instead of the workflow's whole history. Workflow "
            "metrics only; ignored elsewhere. Use it to compare a change against the version before it."
        ),
    )


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
        {"AND instance_id = %(instance_id)s" if instance_id else ""}
        {"AND metric_name IN %(name)s" if name else ""}
        {"AND metric_kind IN %(kind)s" if kind else ""}
        GROUP BY timestamp, breakdown
        ORDER BY timestamp ASC
    """

    clickhouse_kwargs["team_id"] = team_id
    clickhouse_kwargs["app_source"] = app_source
    clickhouse_kwargs["app_source_id"] = app_source_id
    # Convert to UTC before formatting — the naive string is read as UTC by toDateTime64, so a
    # team-timezone-aware bound would otherwise shift the window by the team's offset.
    clickhouse_kwargs["after"] = after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    clickhouse_kwargs["before"] = before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
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

    # Convert to UTC before formatting — the naive string is read as UTC by toDateTime64, so a
    # team-timezone-aware bound would otherwise shift the window by the team's offset.
    clickhouse_kwargs: dict[str, Any] = {
        "team_id": team_id,
        "app_source": app_source,
        "app_source_id": app_source_id,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if after else None,
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
        "instance_id": instance_id,
        "name": name,
        "kind": kind,
    }

    clickhouse_query = f"""
        SELECT
            metric_{breakdown_by} as breakdown,
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND app_source_id = %(app_source_id)s
        {"AND timestamp >= toDateTime64(%(after)s, 6)" if after else ""}
        {"AND timestamp <= toDateTime64(%(before)s, 6)" if before else ""}
        {"AND instance_id = %(instance_id)s" if instance_id else ""}
        {"AND metric_name IN %(name)s" if name else ""}
        {"AND metric_kind IN %(kind)s" if kind else ""}
        GROUP BY breakdown
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals = {row[0]: row[1] for row in results}
    return AppMetricsTotalsResponse(totals=totals)


def fetch_app_metric_totals_by_source(
    team_id: int,
    app_source: str,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    name: Optional[list[str]] = None,
) -> dict[str, dict[str, int]]:
    """Per-`app_source_id` metric totals for a whole team in one grouped query.

    Unlike `fetch_app_metric_totals` (single object), this drops the `app_source_id`
    filter and groups by it, so callers get counts for every object at once — e.g. a
    failure overview across all workflows. Returns `{app_source_id: {metric_name: count}}`.
    """
    name = name or ["succeeded", "failed"]

    # Convert to UTC before formatting — the naive string is read as UTC by toDateTime64, so a
    # team-timezone-aware bound would otherwise shift the window by the team's offset.
    clickhouse_kwargs: dict[str, Any] = {
        "team_id": team_id,
        "app_source": app_source,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if after else None,
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
        "name": name,
    }

    clickhouse_query = f"""
        SELECT
            app_source_id,
            metric_name,
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        {"AND timestamp >= toDateTime64(%(after)s, 6)" if after else ""}
        {"AND timestamp <= toDateTime64(%(before)s, 6)" if before else ""}
        AND metric_name IN %(name)s
        GROUP BY app_source_id, metric_name
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals: dict[str, dict[str, int]] = {}
    for app_source_id, metric_name, count in results:
        totals.setdefault(app_source_id, {})[metric_name] = count
    return totals


def fetch_app_metric_totals_by_team_and_source(
    app_source: str,
    name: list[str],
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    team_ids: Optional[list[int]] = None,
    min_totals: Optional[dict[str, int]] = None,
    any_min_totals: Optional[dict[str, int]] = None,
) -> dict[int, dict[str, dict[str, int]]]:
    """Per-`app_source_id` metric totals across many teams in one grouped query.

    Unlike `fetch_app_metric_totals_by_source` (one team), this groups by `team_id` as
    well, so a background sweep gets the whole fleet from a single query instead of a
    query per team. Returns `{team_id: {app_source_id: {metric_name: count}}}`.

    Each requested metric name becomes its own `sumIf` column, which is what lets the
    thresholds be pushed down: `min_totals` requires every named metric to reach its
    value and `any_min_totals` requires at least one to, both evaluated in `HAVING`. Use
    a pushdown, a `team_ids` list, or both. Unfiltered, the result set grows with the
    fleet, and a sweep that has to stream every object's counts back to Python stops
    being affordable.
    """
    if not name:
        raise ValueError("At least one metric name is required")

    # Convert to UTC before formatting — the naive string is read as UTC by toDateTime64, so a
    # team-timezone-aware bound would otherwise shift the window by the team's offset.
    clickhouse_kwargs: dict[str, Any] = {
        "app_source": app_source,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if after else None,
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
        "name": name,
        "team_ids": team_ids,
    }

    # Alias per metric rather than the metric name itself: metric names are caller-supplied and
    # would have to be interpolated raw into the SQL to be usable as identifiers.
    aliases = {metric_name: f"metric_{index}" for index, metric_name in enumerate(name)}
    for metric_name, alias in aliases.items():
        clickhouse_kwargs[f"{alias}_name"] = metric_name

    selects = ", ".join(f"sumIf(count, metric_name = %({alias}_name)s) AS {alias}" for alias in aliases.values())

    having_clauses: list[str] = []
    for metric_name, minimum in (min_totals or {}).items():
        alias = aliases[metric_name]
        clickhouse_kwargs[f"{alias}_min"] = minimum
        having_clauses.append(f"{alias} >= %({alias}_min)s")
    any_clauses: list[str] = []
    for metric_name, minimum in (any_min_totals or {}).items():
        alias = aliases[metric_name]
        clickhouse_kwargs[f"{alias}_any_min"] = minimum
        any_clauses.append(f"{alias} >= %({alias}_any_min)s")
    if any_clauses:
        having_clauses.append(f"({' OR '.join(any_clauses)})")

    clickhouse_query = f"""
        SELECT
            team_id,
            app_source_id,
            {selects}
        FROM app_metrics2
        WHERE app_source = %(app_source)s
        {"AND team_id IN %(team_ids)s" if team_ids else ""}
        {"AND timestamp >= toDateTime64(%(after)s, 6)" if after else ""}
        {"AND timestamp <= toDateTime64(%(before)s, 6)" if before else ""}
        AND metric_name IN %(name)s
        GROUP BY team_id, app_source_id
        {f"HAVING {' AND '.join(having_clauses)}" if having_clauses else ""}
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals: dict[int, dict[str, dict[str, int]]] = {}
    for row in results:
        team_id, app_source_id = row[0], row[1]
        totals.setdefault(team_id, {})[app_source_id] = dict(zip(name, (int(value) for value in row[2:])))
    return totals


def fetch_app_metric_daily_totals_by_team(
    app_source: str,
    name: list[str],
    after: datetime,
    before: Optional[datetime] = None,
    team_ids: Optional[list[int]] = None,
    workload: Workload = Workload.DEFAULT,
) -> dict[int, dict[str, dict[str, int]]]:
    """Daily metric totals per team, keyed `{team_id: {"YYYY-MM-DD": {metric_name: count}}}`.

    Days rather than a single total, because "sent at least X on each of N days" cannot be told
    apart from one burst of the same size once the window is summed.

    Called without team_ids, the daily tier sweep scans the whole fleet. The result is bounded per
    team, at most one row per metric name per day, but it grows linearly with the number of sending
    teams because app_source alone does not prune the app_metrics2 primary key. This is affordable at
    the current scale and runs on the LONG_RUNNING queue. If the sending fleet grows large, batch by
    team or aggregate to one row per team here.
    """
    clickhouse_kwargs: dict[str, Any] = {
        "app_source": app_source,
        "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") if before else None,
        "name": name,
        "team_ids": team_ids,
    }

    clickhouse_query = f"""
        SELECT
            team_id,
            toDate(timestamp) as day,
            metric_name,
            sum(count) as count
        FROM app_metrics2
        WHERE app_source = %(app_source)s
        {"AND team_id IN %(team_ids)s" if team_ids else ""}
        AND timestamp >= toDateTime64(%(after)s, 6)
        {"AND timestamp <= toDateTime64(%(before)s, 6)" if before else ""}
        AND metric_name IN %(name)s
        GROUP BY team_id, day, metric_name
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs, workload=workload)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals: dict[int, dict[str, dict[str, int]]] = {}
    for team_id, day, metric_name, count in results:
        totals.setdefault(team_id, {}).setdefault(day.strftime("%Y-%m-%d"), {})[metric_name] = count
    return totals


class AppMetricsMixin(viewsets.GenericViewSet):
    app_source: str  # Should be set by the inheriting class

    def get_app_metrics_instance_id(self) -> Optional[str]:
        """
        Can be used overridden to help with getting the instance_id for the app metrics.
        Otherwise it defaults to null or the query param if given
        """
        raise NotImplementedError()

    @extend_schema(parameters=[AppMetricsRequestSerializer], responses=AppMetricResponseSerializer)
    @action(detail=True, methods=["GET"])
    def metrics(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        param_serializer = AppMetricsRequestSerializer(data=request.query_params)

        if not self.app_source:
            raise ValidationError("app_source not set on the viewset")

        product_key = APP_SOURCE_TO_PRODUCT_KEY.get(self.app_source, ProductKey.PIPELINE_DESTINATIONS)
        tag_queries(product=product_key, feature=Feature.QUERY)

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

        series = self._metric_series_for(obj, params.get("version"))
        data = fetch_app_metrics_trends(
            team_id=self.team_id,  # type: ignore
            app_source=series.app_source,
            app_source_id=series.app_source_id,
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

    def _metric_series_for(self, obj, version: int | None) -> "MetricSeries":
        """Which app-metric series to read: the object's whole history, or one workflow version.

        Every hog flow metric is mirrored under `hog_flow_version` with the version appended to the
        id, which is what makes "before and after this change" answerable at all. Nothing mirrors
        hog function metrics that way, so a version there would silently read an empty series.
        """
        if version is not None and self.app_source == "hog_flow":
            return MetricSeries(app_source=HOG_FLOW_VERSION_APP_SOURCE, app_source_id=f"{obj.id}/{version}")
        return MetricSeries(app_source=self.app_source, app_source_id=str(obj.id))

    @extend_schema(parameters=[AppMetricsRequestSerializer], responses=AppMetricsTotalsResponseSerializer)
    @action(detail=True, methods=["GET"], url_path="metrics/totals")
    def metrics_totals(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        param_serializer = AppMetricsRequestSerializer(data=request.query_params)

        if not self.app_source:
            raise ValidationError("app_source not set on the viewset")

        product_key = APP_SOURCE_TO_PRODUCT_KEY.get(self.app_source, ProductKey.PIPELINE_DESTINATIONS)
        tag_queries(product=product_key, feature=Feature.QUERY)

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

        series = self._metric_series_for(obj, params.get("version"))
        data = fetch_app_metric_totals(
            team_id=self.team_id,  # type: ignore
            app_source=series.app_source,
            app_source_id=series.app_source_id,
            # From request params
            after=after_date,
            before=before_date,
            breakdown_by=params.get("breakdown_by"),
            name=params["name"].split(",") if params.get("name") else None,
            kind=params["kind"].split(",") if params.get("kind") else None,
        )

        serializer = AppMetricsTotalsResponseSerializer(instance=data)
        return Response(serializer.data)
