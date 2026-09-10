from dataclasses import field
from typing import Any, Optional

import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.labeling import (
    IDENTIFIED_USERS_ONLY,
    _build_population_conditions,
    _build_population_kind_conditions,
    _identified_users_and_clause,
    _target_condition_for,
    build_eligible_count_sql,
    build_random_t0_labeler_sql,
)
from products.autoresearch.backend.query import run_hogql_rows

logger = structlog.get_logger(__name__)

# Minimum number of labeled examples needed to train a meaningful model. Both classes
# need examples: holdout AUC is undefined when every label is the same.
MIN_TRAINING_ROWS = 100
MIN_POSITIVE_EXAMPLES = 20
MIN_NEGATIVE_EXAMPLES = 20

# Warn when fewer than this fraction of the population is identified — under the v1
# identified-only scope the anonymous remainder is silently excluded, so flag it.
MIN_IDENTIFIED_FRACTION = 0.5

# Cap the user_window CTE during live wizard estimates — sampled base rate is
# unbiased for the same quantity the trainer computes unsampled.
LIVE_ESTIMATE_SAMPLE_LIMIT = 5_000


def inference_lookback_days(horizon_days: int) -> int:
    # The window the scorer binds when it builds inference anchors (4x horizon, min 30),
    # so the previewed population is the one that will actually be scored.
    return max(30, horizon_days * 4)


@frozen
class ValidationWarning:
    code: str
    message: str
    severity: str  # "info" | "warning" | "error"


@frozen
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
    target_definition: dict[str, Any] | None = None,
    user: User | None = None,
) -> ValidationResult:
    """
    Validate a proposed pipeline definition against real team data.

    Runs HogQL count queries to estimate volume, base rate, and catch common
    mistakes before training is triggered. `user` is the person HogQL applies
    access control for; without one the counts can be masked from data the
    requester may read.
    """
    try:
        return _run_validation(
            team=team,
            target_event=target_event,
            target_definition=target_definition,
            horizon_days=horizon_days,
            training_lookback_days=training_lookback_days,
            training_population=training_population,
            inference_population=inference_population,
            user=user,
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
    target_definition: dict[str, Any] | None = None,
    user: User | None = None,
) -> ValidationResult:
    tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)

    # Headline eligible count — true number of users that would be labeled by the
    # random-T0 labeler, no sampling. Used for the UI's "Training rows" metric and
    # volume warnings.
    eligible_sql, eligible_values = build_eligible_count_sql(
        horizon_days=horizon_days,
        lookback_days=training_lookback_days,
        training_population=training_population,
        target_event=target_event,
        target_definition=target_definition,
        team=team,
    )
    eligible_rows = run_hogql_rows(team=team, query=HogQLQuery(query=eligible_sql, values=eligible_values), user=user)
    # eligible = identified-only headline (v1); eligible_all = same count without the
    # identified restriction, used to detect a mostly-anonymous population.
    total_users = 0
    total_users_all = 0
    if eligible_rows:
        row = eligible_rows[0]
        total_users = int(row[0] or 0)
        total_users_all = int(row[1] or 0) if len(row) > 1 else total_users

    # Sampled random-T0 labeler — each user is assigned a deterministic random T0 in
    # their history and labeled by whether target_event fires in [T0, T0 + horizon).
    # Sampled at LIVE_ESTIMATE_SAMPLE_LIMIT for fast wizard feedback; the resulting
    # base_rate is an unbiased estimator of the trainer's unsampled rate.
    label_sql, label_values = build_random_t0_labeler_sql(
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        horizon_days=horizon_days,
        lookback_days=training_lookback_days,
        training_population=training_population,
        sample_limit=LIVE_ESTIMATE_SAMPLE_LIMIT,
    )
    label_rows = run_hogql_rows(team=team, query=HogQLQuery(query=label_sql, values=label_values), user=user)
    sampled_users = 0
    sampled_positives = 0
    if label_rows:
        row = label_rows[0]
        sampled_users = int(row[0] or 0)
        sampled_positives = int(row[1] or 0)

    base_rate = sampled_positives / sampled_users if sampled_users > 0 else 0.0
    # Extrapolate sample-rate to the full eligible population for the headline counts.
    positives = round(base_rate * total_users) if total_users > 0 else 0
    negatives = total_users - positives

    # Inference population: distinct users matching the prediction filter over the
    # window the scorer binds. Always counted, even with no filter, so the preview
    # stays aligned with what `build_inference_anchors_sql` scores.
    inference_properties = (inference_population or {}).get("properties", []) if inference_population else []
    # Template populations carry a `kind` rather than raw properties, so compile it through
    # the same helper scoring uses — counting every identified user would preview a
    # population the pipeline will never score.
    target_cond, target_values = _target_condition_for(
        inference_population, target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_inference_kind = _build_population_kind_conditions(inference_population, target_cond=target_cond)
    inf_parts, inf_values = _build_population_conditions(inference_properties)
    inf_parts.extend(compiled_inference_kind.where_parts)
    inf_values.update(target_values)
    inf_values.update(compiled_inference_kind.values)
    inference_clause = f" AND ({' AND '.join(inf_parts)})" if inf_parts else ""
    inference_query = HogQLQuery(
        query=f"""
            SELECT countDistinct(person_id) AS users
            FROM events
            WHERE timestamp >= now() - toIntervalDay({{lookback}})
              AND timestamp < now(){inference_clause}{_identified_users_and_clause()}
        """,
        values={"lookback": inference_lookback_days(horizon_days), **inf_values},
    )
    inf_rows = run_hogql_rows(team=team, query=inference_query, user=user)
    inference_size = int(inf_rows[0][0] or 0) if inf_rows else 0

    warnings = _build_warnings(
        total_users=total_users,
        total_users_all=total_users_all,
        positives=positives,
        negatives=negatives,
        base_rate=base_rate,
        lookback_days=training_lookback_days,
        target_event=target_event,
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


def _build_warnings(
    *,
    total_users: int,
    total_users_all: int,
    positives: int,
    negatives: int,
    base_rate: float,
    lookback_days: int,
    target_event: str,
) -> list[ValidationWarning]:
    warnings: list[ValidationWarning] = []

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
                message=f"{total_users} users found. The model may have limited accuracy with this volume.",
                severity="warning",
            )
        )

    # Mostly-anonymous population — under the v1 identified-only scope the anonymous
    # remainder is excluded from training and scoring, which can shrink the population
    # well below what the user expects. Warn so the exclusion is visible.
    if IDENTIFIED_USERS_ONLY and total_users_all > 0:
        identified_fraction = total_users / total_users_all
        if identified_fraction < MIN_IDENTIFIED_FRACTION:
            excluded = total_users_all - total_users
            warnings.append(
                ValidationWarning(
                    code="mostly_anonymous_population",
                    message=f"Only {identified_fraction:.0%} of this population is identified. "
                    f"Autoresearch models identified users only, so {excluded} anonymous "
                    f"user(s) are excluded from training and scoring.",
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

    if negatives < MIN_NEGATIVE_EXAMPLES:
        warnings.append(
            ValidationWarning(
                code="low_negatives",
                message=f"Only {negatives} users did not perform '{target_event}'. "
                f"At least {MIN_NEGATIVE_EXAMPLES} negative examples are needed.",
                severity="error",
            )
        )

    # Extreme imbalance
    if total_users > 0 and base_rate < 0.01:
        warnings.append(
            ValidationWarning(
                code="extreme_imbalance",
                message=f"Base rate is {base_rate:.2%}. Very rare events need a larger population "
                "for reliable calibration.",
                severity="warning",
            )
        )
    elif total_users > 0 and base_rate > 0.95:
        warnings.append(
            ValidationWarning(
                code="near_universal",
                message=f"Base rate is {base_rate:.2%}. Almost everyone does this event, "
                "so the model may not add much predictive value.",
                severity="warning",
            )
        )

    return warnings
