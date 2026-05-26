from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

# Minimum number of labeled examples needed to train a meaningful model
MIN_TRAINING_ROWS = 100
MIN_POSITIVE_EXAMPLES = 20


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
    prediction_mode: str,
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
            prediction_mode=prediction_mode,
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
    prediction_mode: str,
    training_population: dict[str, Any],
    inference_population: dict[str, Any],
) -> ValidationResult:
    warnings: list[ValidationWarning] = []

    # Count distinct users who did the target event in the last (horizon_days * 4) lookback
    lookback_days = max(horizon_days * 4, 30)

    count_query = HogQLQuery(
        query="""
            SELECT
                countDistinctIf(person_id, event = {target}) AS positives,
                countDistinct(person_id) AS total_users
            FROM events
            WHERE timestamp >= now() - toIntervalDay({lookback})
              AND timestamp < now()
        """,
        values={"target": target_event, "lookback": lookback_days},
    )

    tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
    runner = HogQLQueryRunner(query=count_query, team=team)
    result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

    positives = 0
    total_users = 0
    if result.results and len(result.results) > 0:
        row = result.results[0]
        positives = int(row[0] or 0)
        total_users = int(row[1] or 0)

    negatives = total_users - positives
    base_rate = positives / total_users if total_users > 0 else 0.0

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

    # Adoption vs continuation coherence check
    if prediction_mode == "adoption" and base_rate > 0.5:
        warnings.append(
            ValidationWarning(
                code="adoption_high_base_rate",
                message=f"Prediction mode is 'adoption' but {base_rate:.0%} of users have already done "
                f"'{target_event}'. Consider 'continuation' mode or tightening the population.",
                severity="warning",
            )
        )
    elif prediction_mode == "continuation" and base_rate < 0.2:
        warnings.append(
            ValidationWarning(
                code="continuation_low_base_rate",
                message=f"Prediction mode is 'continuation' but only {base_rate:.0%} of users have done "
                f"'{target_event}'. Consider 'adoption' mode.",
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
        inference_population_size=total_users,
        warnings=warnings,
    )
