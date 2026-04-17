from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from django.db.models import Q

import numpy as np
import structlog
import temporalio.activity

from posthog.schema import IntervalType

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.models.anomaly import InsightAnomalyConfig
from posthog.sync import database_sync_to_async
from posthog.tasks.alerts.detector import _compute_min_samples_for_detector, _date_range_override_for_detector
from posthog.temporal.anomalies.common import (
    DEFAULT_ANOMALY_DETECTOR_CONFIG,
    MIN_TRAIN_POINTS,
    RETRAIN_CADENCE,
    interval_from_query,
    is_anomalies_enabled_for_team,
    is_time_series_trends_insight,
    tune_training_config_for_interval,
)
from posthog.temporal.anomalies.model_storage import save_model
from posthog.temporal.anomalies.trainable_ensemble import TrainableEnsemble
from posthog.temporal.anomalies.types import ScheduleTrainingInputs, TrainInsightActivityInputs, TrainInsightResult

LOGGER = structlog.get_logger(__name__)


@temporalio.activity.defn
async def fetch_insights_needing_training(inputs: ScheduleTrainingInputs) -> list[TrainInsightActivityInputs]:
    @database_sync_to_async(thread_sensitive=False)
    def _fetch() -> list[TrainInsightActivityInputs]:
        now = datetime.now(UTC)

        # Insights that have never been trained OR are stale
        needs_training = Q(last_trained_at__isnull=True)
        for interval_str, cadence in RETRAIN_CADENCE.items():
            stale_cutoff = now - cadence
            needs_training |= Q(interval=interval_str, last_trained_at__lte=stale_cutoff)

        configs = list(
            InsightAnomalyConfig.objects.filter(excluded=False)
            .filter(needs_training)
            .select_related("insight__team")
            .order_by("last_trained_at")[: inputs.batch_size]
        )

        # Filter by feature flag
        team_flag_cache: dict[int, bool] = {}
        due: list[TrainInsightActivityInputs] = []
        for config in configs:
            team = config.insight.team
            if team.id not in team_flag_cache:
                team_flag_cache[team.id] = is_anomalies_enabled_for_team(team)
            if not team_flag_cache[team.id]:
                continue

            due.append(
                TrainInsightActivityInputs(
                    insight_id=config.insight_id,
                    team_id=config.insight.team_id,
                    detector_config=config.detector_config or DEFAULT_ANOMALY_DETECTOR_CONFIG,
                )
            )
        return due

    return await _fetch()


@temporalio.activity.defn
async def train_insight(inputs: TrainInsightActivityInputs) -> TrainInsightResult:
    @database_sync_to_async(thread_sensitive=False)
    def _train() -> TrainInsightResult:
        now = datetime.now(UTC)
        try:
            config = InsightAnomalyConfig.objects.select_related("insight__team").get(insight_id=inputs.insight_id)
        except InsightAnomalyConfig.DoesNotExist:
            return TrainInsightResult(insight_id=inputs.insight_id, error="Config not found")

        insight = config.insight
        is_eligible, trends_query = is_time_series_trends_insight(insight)
        if not is_eligible or trends_query is None:
            return TrainInsightResult(insight_id=inputs.insight_id, error="Not eligible")

        raw_detector_config = inputs.detector_config or DEFAULT_ANOMALY_DETECTOR_CONFIG
        # Size the training window to the insight's interval (e.g. 2 weeks
        # of hourly context, 3 months of daily) so the detector learns a
        # realistic seasonal baseline rather than the alerts system's default
        # 30-point window.
        interval_str = interval_from_query(trends_query)
        detector_config = tune_training_config_for_interval(raw_detector_config, interval_str)

        # Heavy ClickHouse query: fetch full training window
        min_samples = _compute_min_samples_for_detector(detector_config)
        filters_override = _date_range_override_for_detector(trends_query, min_samples)
        # Floor for "do we have enough history to bother?" Independent of the
        # detector's statistical floor: a series can be technically trainable
        # (≥10 points) yet still produce noisy output if we haven't covered
        # enough of a seasonal cycle.
        min_points_required = MIN_TRAIN_POINTS.get(interval_str, 10)

        execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        if trends_query.interval == IntervalType.HOUR:
            execution_mode = ExecutionMode.CALCULATE_BLOCKING_ALWAYS

        calculation_result = calculate_for_query_based_insight(
            insight,
            team=insight.team,
            execution_mode=execution_mode,
            user=None,
            filters_override=filters_override,
        )

        if not calculation_result.result:
            return TrainInsightResult(insight_id=inputs.insight_id, error="No results")

        results = cast(list[dict[str, Any]], calculation_result.result)
        ensemble = TrainableEnsemble(detector_config)

        # Train on each series, store a single fitted ensemble per series
        # For now we train on the first non-compare series as the representative
        # (the trained model captures the statistical properties of the data)
        series_models: dict[int, bytes] = {}
        for series_index, series_result in enumerate(results):
            if series_result.get("compare") or series_result.get("status") is not None:
                continue

            data_list = series_result.get("data", [])
            if len(data_list) < min_points_required:
                continue

            data = np.array(data_list, dtype=float)
            if not np.all(np.isfinite(data)):
                continue

            try:
                fitted = ensemble.train(data)
                series_models[series_index] = fitted.serialize()
            except Exception as e:
                LOGGER.warning(
                    "anomaly_train_series_failed", insight_id=inputs.insight_id, series_index=series_index, error=str(e)
                )
                continue

        if not series_models:
            return TrainInsightResult(insight_id=inputs.insight_id, error="No trainable series")

        # Store all series models as a single blob
        import pickle

        combined_blob = pickle.dumps(series_models)
        new_version = config.model_version + 1

        from posthog.temporal.anomalies.trainable_ensemble import FittedEnsemble

        # Wrap in a FittedEnsemble-like structure for storage
        wrapper = FittedEnsemble(
            sub_models=[],
            operator=detector_config.get("operator", "or"),
            trained_at=now,
            training_samples=len(results),
            config=detector_config,
        )
        # Store the raw series_models dict directly
        key = save_model(config.insight.team_id, inputs.insight_id, new_version, wrapper)

        # Actually store the per-series blob (overwrite with the real data)
        from posthog.storage import object_storage

        object_storage.write(key, combined_blob)

        config.last_trained_at = now
        config.model_storage_key = key
        config.model_version = new_version
        config.save(update_fields=["last_trained_at", "model_storage_key", "model_version"])

        return TrainInsightResult(insight_id=inputs.insight_id, trained=True, model_version=new_version)

    return await _train()
