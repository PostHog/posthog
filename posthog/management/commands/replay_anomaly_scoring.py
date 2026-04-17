"""Replay anomaly training + scoring over historical demo data.

Simulates what the natural hourly train / 5-min score Temporal schedules would
have produced if they'd been running over the past N days. Useful for seeding
the Anomalies tab on a fresh dev machine with rich historical data.

For each eligible InsightAnomalyConfig on a team, walks a virtual_now from
`window_start` forward to real now, stepping by the insight's interval. At each
tick: retrains if the model is stale per RETRAIN_CADENCE, then scores the
latest data point (as seen from that virtual_now), writing an AnomalyScore.

Not part of any automated job — invoke manually via `manage.py`.
"""
# ruff: noqa: T201

from __future__ import annotations

import pickle
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django.core.management.base import BaseCommand

import numpy as np
from dateutil.relativedelta import relativedelta

from posthog.schema import IntervalType

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models.anomaly import AnomalyScore, InsightAnomalyConfig
from posthog.models.insight import Insight, InsightViewed
from posthog.storage import object_storage
from posthog.tasks.alerts.detector import _compute_min_samples_for_detector
from posthog.temporal.anomalies.common import (
    DEFAULT_ANOMALY_DETECTOR_CONFIG,
    INTERVAL_DELTA,
    RETRAIN_CADENCE,
    SPARKLINE_POINTS,
    interval_from_query,
    is_time_series_trends_insight,
    min_points_for_scoring,
)
from posthog.temporal.anomalies.model_storage import save_model
from posthog.temporal.anomalies.trainable_ensemble import FittedEnsemble, TrainableEnsemble

DEFAULT_DAYS_BACK = {
    "hour": 7,
    "day": 30,
    "week": 180,
    "month": 365,
}


class Command(BaseCommand):
    help = "Replay anomaly training + scoring cadence backwards over historical demo data"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to replay scoring for")
        parser.add_argument(
            "--days-back-hourly",
            type=int,
            default=DEFAULT_DAYS_BACK["hour"],
            help=f"Replay window for hourly insights (default: {DEFAULT_DAYS_BACK['hour']} days)",
        )
        parser.add_argument(
            "--days-back-daily",
            type=int,
            default=DEFAULT_DAYS_BACK["day"],
            help=f"Replay window for daily insights (default: {DEFAULT_DAYS_BACK['day']} days)",
        )
        parser.add_argument(
            "--insight-id",
            type=int,
            default=None,
            help="Only replay this specific insight (default: all eligible on the team)",
        )
        parser.add_argument(
            "--wipe-scores",
            action="store_true",
            default=False,
            help="Delete all existing AnomalyScore rows for this team before replaying",
        )
        parser.add_argument(
            "--recently-viewed-days",
            type=int,
            default=30,
            help="Only include insights viewed in the last N days (default: 30)",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        insight_id: int | None = options["insight_id"]
        now = datetime.now(UTC)

        days_back_by_interval = {
            "hour": options["days_back_hourly"],
            "day": options["days_back_daily"],
            "week": DEFAULT_DAYS_BACK["week"],
            "month": DEFAULT_DAYS_BACK["month"],
        }

        if options["wipe_scores"]:
            deleted, _ = AnomalyScore.objects.filter(team_id=team_id).delete()
            print(f"[replay] wiped {deleted} existing AnomalyScore rows for team {team_id}")

        self._ensure_configs(team_id, now, recently_viewed_days=options["recently_viewed_days"])

        config_qs = InsightAnomalyConfig.objects.filter(team_id=team_id, excluded=False).select_related("insight__team")
        if insight_id is not None:
            config_qs = config_qs.filter(insight_id=insight_id)

        configs = list(config_qs)
        print(f"[replay] {len(configs)} config(s) to replay on team {team_id}")

        for config in configs:
            self._replay_config(config, now, days_back_by_interval)

        print("[replay] done")

    def _ensure_configs(self, team_id: int, now: datetime, recently_viewed_days: int) -> None:
        """Create InsightAnomalyConfig for eligible recently-viewed insights that don't have one."""
        cutoff = now - timedelta(days=recently_viewed_days)
        recently_viewed_ids = set(
            InsightViewed.objects.filter(team_id=team_id, last_viewed_at__gte=cutoff).values_list(
                "insight_id", flat=True
            )
        )
        existing_ids = set(InsightAnomalyConfig.objects.filter(team_id=team_id).values_list("insight_id", flat=True))
        missing_ids = recently_viewed_ids - existing_ids
        created = 0
        for insight in Insight.objects.filter(id__in=missing_ids, deleted=False, query__isnull=False):
            is_eligible, trends_query = is_time_series_trends_insight(insight)
            if not is_eligible or trends_query is None:
                continue
            interval = interval_from_query(trends_query)
            InsightAnomalyConfig.objects.create(
                team_id=team_id,
                insight=insight,
                interval=interval,
                detector_config=DEFAULT_ANOMALY_DETECTOR_CONFIG,
                next_score_due_at=now,
            )
            created += 1
        if created:
            print(f"[replay] created {created} new InsightAnomalyConfig rows on team {team_id}")

    def _replay_config(
        self,
        config: InsightAnomalyConfig,
        now: datetime,
        days_back_by_interval: dict[str, int],
    ) -> None:
        insight = config.insight
        is_eligible, trends_query = is_time_series_trends_insight(insight)
        if not is_eligible or trends_query is None:
            print(f"[replay]   insight {insight.id}: not eligible, skipping")
            return

        interval_str = interval_from_query(trends_query)
        detector_config = config.detector_config or DEFAULT_ANOMALY_DETECTOR_CONFIG
        step = INTERVAL_DELTA[interval_str]
        retrain_cadence = RETRAIN_CADENCE[interval_str]

        days_back = days_back_by_interval.get(interval_str, 30)
        window_start = _floor_to_interval(now - timedelta(days=days_back), interval_str)
        virtual_now = window_start

        print(
            f"[replay]   insight {insight.id} ({interval_str}): "
            f"{insight.name or insight.derived_name or 'unnamed'} — "
            f"window {window_start:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M}"
        )

        # Train fresh at window_start so the replay starts with a calibrated model.
        model_payload = _train_at(insight, trends_query, detector_config, virtual_now)
        if model_payload is None:
            print(f"[replay]   insight {insight.id}: initial training failed, skipping")
            return
        self._persist_model(config, model_payload, virtual_now, detector_config)
        last_trained_virtual = virtual_now
        print(f"[replay]     trained initial model at {virtual_now:%Y-%m-%d %H:%M}")

        ticks = 0
        retrains = 1
        scores_written = 0
        series_models = model_payload

        while virtual_now <= now:
            # Retrain if stale per cadence
            if virtual_now - last_trained_virtual >= _relativedelta_as_timedelta(retrain_cadence):
                retrained = _train_at(insight, trends_query, detector_config, virtual_now)
                if retrained is not None:
                    series_models = retrained
                    self._persist_model(config, retrained, virtual_now, detector_config)
                    last_trained_virtual = virtual_now
                    retrains += 1

            n_written = _score_at(
                insight=insight,
                trends_query=trends_query,
                detector_config=detector_config,
                series_models=series_models,
                interval_str=interval_str,
                virtual_now=virtual_now,
            )
            scores_written += n_written

            virtual_now = virtual_now + step
            ticks += 1

        # Align the config with the replay tail state so the real Temporal schedule
        # picks up from here naturally.
        config.interval = interval_str
        config.last_scored_at = now
        config.last_trained_at = last_trained_virtual
        config.next_score_due_at = now + step
        config.save(update_fields=["interval", "last_scored_at", "last_trained_at", "next_score_due_at"])

        print(f"[replay]     ticks={ticks} retrains={retrains} scores_written={scores_written}")

    def _persist_model(
        self,
        config: InsightAnomalyConfig,
        series_models: dict[int, bytes],
        virtual_now: datetime,
        detector_config: dict[str, Any],
    ) -> None:
        new_version = config.model_version + 1
        wrapper = FittedEnsemble(
            sub_models=[],
            operator=detector_config.get("operator", "or"),
            trained_at=virtual_now,
            training_samples=len(series_models),
            config=detector_config,
        )
        key = save_model(config.insight.team_id, config.insight_id, new_version, wrapper)
        # Overwrite the placeholder blob with the real per-series model dict,
        # matching the production train_insight activity.
        object_storage.write(key, pickle.dumps(series_models))

        config.model_storage_key = key
        config.model_version = new_version
        config.last_trained_at = virtual_now
        config.save(update_fields=["model_storage_key", "model_version", "last_trained_at"])


def _train_at(
    insight: Insight,
    trends_query: Any,
    detector_config: dict[str, Any],
    virtual_now: datetime,
) -> dict[int, bytes] | None:
    """Fit per-series models using data up to virtual_now."""
    min_samples = _compute_min_samples_for_detector(detector_config)
    # Overshoot a bit: the query engine may return slightly fewer points than
    # the nominal window when date_to is explicit.
    date_from_iso = _absolute_date_from(virtual_now, trends_query.interval, min_samples + 10)

    filters_override = {"date_from": date_from_iso, "date_to": _iso(virtual_now)}
    execution_mode = (
        ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        if trends_query.interval == IntervalType.HOUR
        else ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    )

    calculation_result = calculate_for_query_based_insight(
        insight,
        team=insight.team,
        execution_mode=execution_mode,
        user=None,
        filters_override=filters_override,
    )
    if not calculation_result.result:
        return None

    results = cast(list[dict[str, Any]], calculation_result.result)
    ensemble = TrainableEnsemble(detector_config)

    series_models: dict[int, bytes] = {}
    for series_index, series_result in enumerate(results):
        if series_result.get("compare") or series_result.get("status") is not None:
            continue
        data_list = series_result.get("data", [])
        if len(data_list) < min_samples:
            continue
        data = np.array(data_list, dtype=float)
        if not np.all(np.isfinite(data)):
            continue
        try:
            fitted = ensemble.train(data)
            series_models[series_index] = fitted.serialize()
        except Exception:
            continue

    return series_models or None


def _score_at(
    *,
    insight: Insight,
    trends_query: Any,
    detector_config: dict[str, Any],
    series_models: dict[int, bytes],
    interval_str: str,
    virtual_now: datetime,
) -> int:
    """Score the latest point as of virtual_now; write AnomalyScore records."""
    sparkline_size = SPARKLINE_POINTS.get(interval_str, 30)
    scoring_needs = min_points_for_scoring(detector_config)
    fetch_points = max(sparkline_size, scoring_needs)

    date_from_iso = _absolute_date_from(virtual_now, trends_query.interval, fetch_points)
    filters_override = {"date_from": date_from_iso, "date_to": _iso(virtual_now)}

    # Always use blocking calculation at replay time — caching across virtual_now
    # ticks would wreck correctness.
    calculation_result = calculate_for_query_based_insight(
        insight,
        team=insight.team,
        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        user=None,
        filters_override=filters_override,
    )
    if not calculation_result.result:
        return 0

    results = cast(list[dict[str, Any]], calculation_result.result)
    ensemble = TrainableEnsemble(detector_config)
    written = 0

    for series_index, series_result in enumerate(results):
        if series_result.get("compare") or series_result.get("status") is not None:
            continue
        if series_index not in series_models:
            continue

        data_list = series_result.get("data", [])
        if len(data_list) < 2:
            continue

        data = np.array(data_list, dtype=float)
        dates: list[str] = series_result.get("days") or series_result.get("labels") or []

        try:
            fitted = FittedEnsemble.deserialize(series_models[series_index])
        except Exception:
            continue
        try:
            result = ensemble.score(data, fitted)
        except Exception:
            continue

        score = result.score if result.score is not None else 0.0
        is_anomalous = result.is_anomaly

        snap_data = data_list[-sparkline_size:]
        snap_dates = dates[-sparkline_size:] if dates else []
        anomaly_index = len(snap_data) - 1 if is_anomalous else None

        label = series_result.get("label", f"Series {series_index}")
        breakdown_value = series_result.get("breakdown_value", "")
        if breakdown_value and str(breakdown_value) != label:
            full_label = f"{label} - {breakdown_value}"
        else:
            full_label = label

        timestamp_str = dates[-1] if dates else None
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                ts = virtual_now
        else:
            ts = virtual_now

        obj, _ = AnomalyScore.objects.update_or_create(
            team_id=insight.team_id,
            insight=insight,
            series_index=series_index,
            timestamp=ts,
            defaults={
                "score": score,
                "is_anomalous": is_anomalous,
                "series_label": full_label[:400],
                "interval": interval_str,
                "data_snapshot": {
                    "data": snap_data,
                    "dates": snap_dates,
                    "anomaly_index": anomaly_index,
                },
            },
        )
        # scored_at uses auto_now_add, which fires on INSERT regardless of the
        # value passed into defaults. A follow-up queryset update bypasses it.
        AnomalyScore.objects.filter(pk=obj.pk).update(scored_at=virtual_now)
        written += 1

    return written


def _absolute_date_from(virtual_now: datetime, interval: IntervalType, points: int) -> str:
    """Return an absolute ISO date_from anchored at virtual_now.

    The query engine resolves relative expressions like `-30d` against the real
    `now`, not against `date_to`, so for historical replay we need absolute
    ISO timestamps on both ends of the window.
    """
    match interval:
        case IntervalType.DAY:
            delta = timedelta(days=points)
        case IntervalType.WEEK:
            delta = timedelta(weeks=points)
        case IntervalType.MONTH:
            delta = timedelta(days=points * 31)
        case _:
            delta = timedelta(hours=points)
    return _iso(virtual_now - delta)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _floor_to_interval(dt: datetime, interval_str: str) -> datetime:
    dt = dt.astimezone(UTC)
    match interval_str:
        case "hour":
            return dt.replace(minute=0, second=0, microsecond=0)
        case "day":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        case "week":
            floored_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return floored_day - timedelta(days=floored_day.weekday())
        case "month":
            return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        case _:
            return dt


def _relativedelta_as_timedelta(rd: relativedelta) -> timedelta:
    """Approximate a relativedelta as a timedelta for comparison against wall deltas."""
    days = (rd.years or 0) * 365 + (rd.months or 0) * 30 + (rd.weeks or 0) * 7 + (rd.days or 0)
    seconds = (rd.hours or 0) * 3600 + (rd.minutes or 0) * 60 + (rd.seconds or 0)
    return timedelta(days=days, seconds=seconds)
