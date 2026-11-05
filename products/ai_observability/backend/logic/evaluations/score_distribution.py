from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.ai_observability.backend.models.evaluation_outcomes import NUMERIC_SCORED_PREDICATE, SCORE_EXPRESSION

from ...facade import contracts
from .overview_queries import EVALUATION_RUNS_WHERE, evaluation_runs_placeholders, run_evaluation_query
from .period import PeriodBounds

# An integer scale of 2 to this many steps gets one bucket per integer, any other scale gets equal buckets.
MAX_INTEGER_BUCKETS = 20
EQUAL_BUCKETS = 10

# Scores outside the configured scale land in the end buckets. The emitter skips such runs, so this only catches
# runs scored before the scale changed. The epsilon keeps a score on a bucket edge in the bucket it starts, where
# float division can land just under it: (0.3 - 0) / 0.1 is 2.9999999999999996.
_HISTOGRAM_QUERY = f"""
SELECT least(greatest(toInt(floor(({SCORE_EXPRESSION} - {{low}}) / {{width}} + 1e-9)), 0), {{last}}) AS bucket, count()
FROM events
WHERE {EVALUATION_RUNS_WHERE} AND {NUMERIC_SCORED_PREDICATE}
GROUP BY bucket
LIMIT {MAX_INTEGER_BUCKETS + 1}
"""


@frozen
class ScoreBuckets:
    low: float
    width: float
    labels: tuple[str, ...]


def score_buckets(scale: contracts.ScoreScale, step: float | None) -> ScoreBuckets | None:
    span = scale.max - scale.min
    if span <= 0:
        return None
    # A 0 to 1 scale is a pair of integers too, but its scores are fractions unless a whole step says otherwise.
    integer_steps = step.is_integer() if step is not None else span >= 2
    if scale.min.is_integer() and scale.max.is_integer() and integer_steps and span <= MAX_INTEGER_BUCKETS:
        # Centering each bucket on its integer keeps a score of 3 in the "3" bucket however it rounds.
        return ScoreBuckets(
            low=scale.min - 0.5,
            width=1,
            labels=tuple(str(int(scale.min) + offset) for offset in range(int(span) + 1)),
        )
    width = span / EQUAL_BUCKETS
    return ScoreBuckets(
        low=scale.min,
        width=width,
        labels=tuple(
            f"{scale.min + index * width:g}-{scale.min + (index + 1) * width:g}" for index in range(EQUAL_BUCKETS)
        ),
    )


def load_score_distribution(
    team: Team,
    user: User | None,
    evaluation_id: str,
    period: PeriodBounds,
    scale: contracts.ScoreScale,
    buckets: ScoreBuckets,
) -> contracts.ScoreHistogram:
    rows = run_evaluation_query(
        "ai_evaluations_score_distribution",
        _HISTOGRAM_QUERY,
        team,
        user,
        {
            **evaluation_runs_placeholders(evaluation_id, period),
            "low": ast.Constant(value=buckets.low),
            "width": ast.Constant(value=buckets.width),
            "last": ast.Constant(value=len(buckets.labels) - 1),
        },
    )
    counts = {int(bucket): count for bucket, count in rows}
    return contracts.ScoreHistogram(
        scale=scale,
        buckets=[
            contracts.ScoreBucket(label=label, count=counts.get(index, 0)) for index, label in enumerate(buckets.labels)
        ],
    )
