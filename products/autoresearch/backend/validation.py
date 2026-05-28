from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.labeling import (
    _build_population_conditions,
    build_eligible_count_sql,
    build_random_t0_labeler_sql,
)

logger = structlog.get_logger(__name__)

# Minimum number of labeled examples needed to train a meaningful model
MIN_TRAINING_ROWS = 100
MIN_POSITIVE_EXAMPLES = 20

# Cap the user_window CTE during live wizard estimates — sampled base rate is
# unbiased for the same quantity the trainer computes unsampled.
LIVE_ESTIMATE_SAMPLE_LIMIT = 5_000


@dataclass
class ValidationWarning:
    code: str
    message: str
    severity: str  # "info" | "warning" | "error"


@dataclass
class ValidationResult:
    can_proceed: bool
    requires_acknowledgement: bool
    estimated_training_rows: Optional[int]
    positive_count: Optional[int]
    negative_count: Optional[int]
    base_rate: Optional[float]
    inference_population_size: Optional[int]
    warnings: list[ValidationWarning] = field(default_factory=list)
    error: Optional[str] = None


def validate_pipeline_definition(
    team: Team,
    target_event: str,
    horizon_days: int,
    training_lookback_days: int,
    training_population: dict[str, Any],
    inference_population: dict[str, Any],
) -> ValidationResult:
    """
    Validate a proposed pipeline definition against real team data.

    Runs HogQL count queries to estimate volume, base rate, and catch common
    mistakes before training is triggered.
    """
    try:
        return _run_validation(
            team=team,
            target_event=target_event,
            horizon_days=horizon_days,
            training_lookback_days=training_lookback_days,
            training_population=training_population,
            inference_population=inference_population,
        )
    except Exception as exc:
        logger.exception("autoresearch_validation_error", team_id=team.pk, target_event=target_event)
        return ValidationResult(
            can_proceed=False,
            requires_acknowledgement=False,
            estimated_training_rows=None,
            positive_count=None,
            negative_count=None,
            base_rate=None,
            inference_population_size=None,
            error=str(exc),
        )


def _run_validation(
    *,
    team: Team,
    target_event: str,
    horizon_days: int,
    training_lookback_days: int,
    training_population: dict[str, Any],
    inference_population: dict[str, Any],
) -> ValidationResult:
    warnings: list[ValidationWarning] = []

    # Use the explicit training lookback window. Clamp to a sane minimum so very short windows
    # still produce a meaningful estimate.
    lookback_days = max(training_lookback_days, 7)

    tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)

    # Headline eligible count — true number of users that would be labeled by the
    # random-T0 labeler, no sampling. Used for the UI's "Training rows" metric and
    # volume warnings.
    eligible_sql, eligible_values = build_eligible_count_sql(
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
    )
    eligible_runner = HogQLQueryRunner(query=HogQLQuery(query=eligible_sql, values=eligible_values), team=team)
    eligible_result = eligible_runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    total_users = 0
    if eligible_result.results and len(eligible_result.results) > 0:
        total_users = int(eligible_result.results[0][0] or 0)

    # Sampled random-T0 labeler — each user is assigned a deterministic random T0 in
    # their history and labeled by whether target_event fires in [T0, T0 + horizon).
    # Sampled at LIVE_ESTIMATE_SAMPLE_LIMIT for fast wizard feedback; the resulting
    # base_rate is an unbiased estimator of the trainer's unsampled rate.
    label_sql, label_values = build_random_t0_labeler_sql(
        target_event=target_event,
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
        sample_limit=LIVE_ESTIMATE_SAMPLE_LIMIT,
    )
    label_runner = HogQLQueryRunner(query=HogQLQuery(query=label_sql, values=label_values), team=team)
    label_result = label_runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    sampled_users = 0
    sampled_positives = 0
    if label_result.results and len(label_result.results) > 0:
        row = label_result.results[0]
        sampled_users = int(row[0] or 0)
        sampled_positives = int(row[1] or 0)

    base_rate = sampled_positives / sampled_users if sampled_users > 0 else 0.0
    # Extrapolate sample-rate to the full eligible population for the headline counts.
    positives = round(base_rate * total_users) if total_users > 0 else 0
    negatives = total_users - positives

    # Inference population — count distinct users matching the prediction filter.
    # If no inference filter is provided we fall back to the training count.
    inference_properties = (inference_population or {}).get("properties", []) if inference_population else []
    if inference_properties:
        inf_parts, inf_values = _build_population_conditions(inference_properties)
        inference_clause = f" AND ({' AND '.join(inf_parts)})" if inf_parts else ""
        inference_query = HogQLQuery(
            query=f"""
                SELECT countDistinct(person_id) AS users
                FROM events
                WHERE timestamp >= now() - toIntervalDay({{lookback}})
                  AND timestamp < now(){inference_clause}
            """,
            values={"lookback": lookback_days, **inf_values},
        )
        inf_runner = HogQLQueryRunner(query=inference_query, team=team)
        inf_result = inf_runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        inference_size = int(inf_result.results[0][0] or 0) if inf_result.results else 0
    else:
        inference_size = total_users

    # Volume warnings
    if total_users < MIN_TRAINING_ROWS:
        warnings.append(
            ValidationWarning(
                code="low_volume",
                message=f"Only {total_users} users found in the last {lookback_days} days. "
                f"At least {MIN_TRAINING_ROWS} are recommended for reliable training.",
                severity="error",
            )
        )
    elif total_users < MIN_TRAINING_ROWS * 5:
        warnings.append(
            ValidationWarning(
                code="moderate_volume",
                message=f"{total_users} users found — model may have limited accuracy with this volume.",
                severity="warning",
            )
        )

    if positives < MIN_POSITIVE_EXAMPLES:
        warnings.append(
            ValidationWarning(
                code="low_positives",
                message=f"Only {positives} users performed '{target_event}'. "
                f"At least {MIN_POSITIVE_EXAMPLES} positive examples are needed.",
                severity="error",
            )
        )

    # Extreme imbalance
    if total_users > 0 and base_rate < 0.01:
        warnings.append(
            ValidationWarning(
                code="extreme_imbalance",
                message=f"Base rate is {base_rate:.2%} — very rare events require special handling "
                "and will need a larger population for reliable calibration.",
                severity="warning",
            )
        )
    elif total_users > 0 and base_rate > 0.95:
        warnings.append(
            ValidationWarning(
                code="near_universal",
                message=f"Base rate is {base_rate:.2%} — almost everyone does this event. "
                "The model may not add much predictive value.",
                severity="warning",
            )
        )

    has_errors = any(w.severity == "error" for w in warnings)
    has_hard_warnings = any(w.severity == "warning" for w in warnings)

    return ValidationResult(
        can_proceed=not has_errors,
        requires_acknowledgement=has_hard_warnings and not has_errors,
        estimated_training_rows=total_users,
        positive_count=positives,
        negative_count=negatives,
        base_rate=base_rate,
        inference_population_size=inference_size,
        warnings=warnings,
    )
