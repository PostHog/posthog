from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db.models import Q, QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.anomaly import AnomalyScore, InsightAnomalyConfig


class AnomalyScoreSerializer(serializers.ModelSerializer):
    insight_name = serializers.SerializerMethodField(help_text="Name of the insight this anomaly belongs to.")
    insight_short_id = serializers.SerializerMethodField(help_text="Short ID for building insight URLs.")

    class Meta:
        model = AnomalyScore
        fields = [
            "id",
            "insight_id",
            "insight_name",
            "insight_short_id",
            "series_index",
            "series_label",
            "timestamp",
            "score",
            "is_anomalous",
            "interval",
            "data_snapshot",
            "scored_at",
        ]
        read_only_fields = fields

    def get_insight_name(self, obj: AnomalyScore) -> str:
        insight = obj.insight
        return insight.name or insight.derived_name or f"Insight {insight.short_id}"

    def get_insight_short_id(self, obj: AnomalyScore) -> str:
        return obj.insight.short_id


WINDOW_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "180d": timedelta(days=180),
    "1y": timedelta(days=365),
}


def _timestamp_to_date_key(ts: datetime, interval: str) -> str:
    """Format a score's timestamp to match the `dates[]` strings in data_snapshot.

    The trends query engine emits `dates[i]` as `"YYYY-MM-DD"` for daily/weekly/
    monthly series and `"YYYY-MM-DD HH:MM:SS"` for hourly. We re-create that
    exact format so we can look up a score's position in the sparkline.
    """
    ts = ts.astimezone(UTC)
    if interval == "hour":
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return ts.strftime("%Y-%m-%d")


def _build_series_rows(scores: list[AnomalyScore]) -> list[dict[str, Any]]:
    """Aggregate raw AnomalyScore rows into one entry per (insight, series).

    Each series is represented by its *latest* score (that record's sparkline
    becomes the chart's data). All anomalous scores for that series whose
    timestamps fall inside the sparkline's date range are mapped to indices
    and returned as `data_snapshot.anomaly_indices` (sorted, oldest → newest).
    Series with zero anomalies in the window are dropped.

    Rows are sorted by max score in the window (descending) so the most
    anomalous series surfaces first — matching the "sorted by score" UI hint.
    """
    grouped: dict[tuple[int, int], list[AnomalyScore]] = defaultdict(list)
    for score in scores:
        grouped[(score.insight_id, score.series_index)].append(score)

    rows: list[dict[str, Any]] = []
    for group in grouped.values():
        anomalous = [s for s in group if s.is_anomalous]
        if not anomalous:
            continue

        latest = max(group, key=lambda s: s.timestamp)
        max_score = max(s.score for s in anomalous)
        latest_anomaly = max(anomalous, key=lambda s: s.timestamp)

        snapshot = dict(latest.data_snapshot or {})
        dates: list[str] = snapshot.get("dates") or []
        date_index = {d: i for i, d in enumerate(dates)}
        anomaly_indices: list[int] = []
        # Align each score record to a sparkline index so the chart can draw
        # a per-point score line on a secondary axis.
        scores_by_index: list[float | None] = [None] * len(dates)
        for s in group:
            key = _timestamp_to_date_key(s.timestamp, s.interval or latest.interval)
            idx = date_index.get(key)
            if idx is None:
                continue
            scores_by_index[idx] = s.score
            if s.is_anomalous and idx not in anomaly_indices:
                anomaly_indices.append(idx)
        anomaly_indices.sort()
        snapshot["anomaly_indices"] = anomaly_indices
        snapshot["scores"] = scores_by_index
        # Keep the legacy singular key pointing at the most recent mark so
        # older clients keep rendering a dot.
        snapshot["anomaly_index"] = anomaly_indices[-1] if anomaly_indices else None

        insight = latest.insight
        total_scored = len(group)
        rows.append(
            {
                "id": f"{latest.insight_id}:{latest.series_index}",
                "insight_id": latest.insight_id,
                "insight_name": insight.name or insight.derived_name or f"Insight {insight.short_id}",
                "insight_short_id": insight.short_id,
                "series_index": latest.series_index,
                "series_label": latest.series_label,
                "timestamp": latest_anomaly.timestamp.isoformat(),
                "score": max_score,
                "is_anomalous": True,
                "interval": latest.interval,
                "data_snapshot": snapshot,
                "scored_at": latest.scored_at.isoformat(),
                "anomaly_count": len(anomalous),
                "scored_count": total_scored,
                # Fraction of scoring ticks in the window that came back
                # anomalous. A high rate means the series is consistently
                # misbehaving, not that it had a single bad moment.
                "anomaly_rate": len(anomalous) / total_scored if total_scored else 0.0,
            }
        )

    # Rate first: a series flagged anomalous on most of its observations in
    # the window is more worth attention than one that spiked once, even if
    # the one-off had a higher peak score. Peak score breaks ties, latest
    # timestamp breaks remaining ties.
    rows.sort(key=lambda r: (r["anomaly_rate"], r["score"], r["timestamp"]), reverse=True)
    return rows


class AnomalyViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Anomaly detection scores for time-series insights."""

    scope_object = "INTERNAL"
    serializer_class = AnomalyScoreSerializer

    def safely_get_queryset(self, queryset: QuerySet | None = None) -> QuerySet:
        return (
            AnomalyScore.objects.filter(team_id=self.team_id)
            .select_related("insight")
            .order_by("-timestamp", "-scored_at")
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="window",
                type=str,
                required=False,
                description="Time window for anomaly scores: 24h, 7d, 30d. Default: 7d.",
            ),
            OpenApiParameter(
                name="min_score",
                type=float,
                required=False,
                description="Minimum anomaly score (0-1). Default: 0 (show all).",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Search insight name or series label.",
            ),
            OpenApiParameter(
                name="interval",
                type=str,
                required=False,
                description="Filter by insight interval: hour, day, week, month.",
            ),
            OpenApiParameter(
                name="anomalous_only",
                type=bool,
                required=False,
                description="Only return anomalous scores. Default: true.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        # Aggregation is one row per (insight, series) within the window.
        # We need BOTH anomalous and non-anomalous scores in that window so
        # the latest score's sparkline covers the full chart context — then
        # we filter the anomalous ones to produce the marker indices.
        queryset = self.safely_get_queryset()

        window = request.query_params.get("window", "7d")
        delta = WINDOW_DELTAS.get(window, timedelta(days=7))
        cutoff = datetime.now(UTC) - delta
        queryset = queryset.filter(scored_at__gte=cutoff)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(insight__name__icontains=search) | Q(series_label__icontains=search))

        interval = request.query_params.get("interval")
        if interval and interval in ("hour", "day", "week", "month"):
            queryset = queryset.filter(interval=interval)

        # Cap raw rows fetched: with replays enabled a series can easily have
        # hundreds of scores. We only need enough to find the latest + the
        # anomalous ones; 5000 covers ~160 series worth of 30d daily replay.
        scores = list(queryset[:5000])
        rows = _build_series_rows(scores)

        # Row-level filters that only apply to the aggregated view.
        min_score = request.query_params.get("min_score")
        if min_score:
            try:
                threshold = float(min_score)
                rows = [r for r in rows if r["score"] >= threshold]
            except (ValueError, TypeError):
                pass

        # `anomalous_only` is implicit — _build_series_rows already drops
        # series with no anomalies in window. We accept the param for API
        # compatibility but it no longer changes results.

        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)

        return Response(rows[:100])

    @action(methods=["POST"], detail=False, url_path="exclude")
    def exclude(self, request: Request, *args, **kwargs) -> Response:
        """Exclude an insight from anomaly scoring."""
        insight_id = request.data.get("insight_id")
        if not insight_id:
            return Response({"detail": "insight_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        config, _ = InsightAnomalyConfig.objects.update_or_create(
            team_id=self.team_id,
            insight_id=insight_id,
            defaults={"excluded": True},
        )
        return Response({"status": "excluded", "insight_id": insight_id})

    @action(methods=["POST"], detail=False, url_path="include")
    def include(self, request: Request, *args, **kwargs) -> Response:
        """Re-include a previously excluded insight in anomaly scoring."""
        insight_id = request.data.get("insight_id")
        if not insight_id:
            return Response({"detail": "insight_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        updated = InsightAnomalyConfig.objects.filter(
            team_id=self.team_id,
            insight_id=insight_id,
        ).update(excluded=False, next_score_due_at=None)

        if not updated:
            return Response({"detail": "No config found for this insight"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"status": "included", "insight_id": insight_id})
