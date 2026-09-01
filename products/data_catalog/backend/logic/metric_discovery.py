"""Find the measures a team computes often enough to be worth proposing as metrics.

The scan runs in two stages because they have very different costs. ClickHouse groups the raw log by
``normalized_query_hash`` first, which turns millions of rows into thousands of query shapes. Python
then parses one representative query per shape and folds the shapes onto the measures they compute.

``normalized_query_hash`` is not the grouping key. It hashes the compiled ClickHouse SQL rather than
the HogQL somebody wrote, so two people who express one metric differently land in different
buckets. It only collapses the same saved query re-run many times, which is most of the log.

Nothing here writes to the catalog. A scan reports what it found and what it could not read.
"""

from __future__ import annotations

import structlog

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

from .measure_fingerprint import MeasureExtractionError, MeasureFingerprint, extract_measures

logger = structlog.get_logger(__name__)

# Two people computing the same number is the signal. A day count is not: an insight that refreshes
# on a schedule produces 90 active days under one identity, so a day bar admits every scheduled
# query in the project. Days rank the survivors instead of admitting them.
DEFAULT_MIN_DISTINCT_USERS = 2

DEFAULT_LOOKBACK_DAYS = 90

DEFAULT_SHAPE_LIMIT = 5000

# The catalog runs its own queries against a team's tables when it probes joins and runs metrics.
# Counting those as usage would let discovery treat its own output as evidence.
_EXCLUDED_PRODUCTS = ("data_catalog", "data_quality")

# groupUniqArray bounds the per-shape arrays so one popular shape cannot pull an unbounded set into
# memory. The union of several capped shapes can understate a very large audience, which never
# changes the admission decision because the bar is 2, and only understates a displayed count.
_MAX_TRACKED_USERS_PER_SHAPE = 200

_QUERY_SHAPES_SQL = """
SELECT
    anyLast(lc_query__query) AS sample_hogql,
    groupUniqArray(%(max_users)s)(lc_user_id) AS user_ids,
    groupUniqArray(toDate(event_time)) AS active_days,
    count() AS runs
FROM query_log_archive
WHERE team_id = %(team_id)s
  AND event_time > now() - toIntervalDay(%(lookback_days)s)
  AND type = 'QueryFinish'
  AND lc_query__query != ''
  AND lc_user_id != 0
  AND lc_product NOT IN %(excluded_products)s
GROUP BY normalized_query_hash
ORDER BY runs DESC
LIMIT %(shape_limit)s
"""


@frozen
class QueryShape:
    """One normalized query shape from the log, with who ran it and on which days."""

    sample_hogql: str
    user_ids: frozenset[int]
    active_days: frozenset[str]
    runs: int


@frozen
class MetricCandidate:
    """A measure several people computed, with the usage that argues for proposing it."""

    fingerprint: MeasureFingerprint
    user_ids: frozenset[int]
    active_days: frozenset[str]
    runs: int
    shape_count: int

    @property
    def distinct_users(self) -> int:
        return len(self.user_ids)

    @property
    def distinct_days(self) -> int:
        return len(self.active_days)

    def evidence_sentence(self) -> str:
        people = "person" if self.distinct_users == 1 else "people"
        days = "day" if self.distinct_days == 1 else "days"
        return f"{self.distinct_users} {people} ran {self.fingerprint.describe()}, across {self.distinct_days} {days}."


@frozen
class DiscoveryScan:
    """What one pass over a team's query log produced, including what it could not read."""

    candidates: tuple[MetricCandidate, ...]
    shapes_read: int
    shapes_unparsed: int
    shapes_without_aggregate: int
    measures_below_bar: int

    @property
    def parse_rate(self) -> float:
        """Share of shapes that parsed as HogQL.

        A low rate means the log is mostly queries this scan cannot read, and any conclusion drawn
        from the candidates covers a small corner of what the team actually runs.
        """
        if self.shapes_read == 0:
            return 0.0
        return (self.shapes_read - self.shapes_unparsed) / self.shapes_read


@frozen(frozen=False)
class _Accumulator:
    fingerprint: MeasureFingerprint
    user_ids: set[int]
    active_days: set[str]
    runs: int
    shape_count: int


def scan_team(
    team_id: int,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    shape_limit: int = DEFAULT_SHAPE_LIMIT,
    min_distinct_users: int = DEFAULT_MIN_DISTINCT_USERS,
) -> DiscoveryScan:
    shapes = fetch_query_shapes(team_id, lookback_days=lookback_days, shape_limit=shape_limit)
    scan = fold_shapes(shapes, min_distinct_users=min_distinct_users)
    logger.info(
        "data_catalog_metric_discovery_scan",
        team_id=team_id,
        shapes_read=scan.shapes_read,
        shapes_unparsed=scan.shapes_unparsed,
        parse_rate=round(scan.parse_rate, 3),
        candidates=len(scan.candidates),
    )
    return scan


def fetch_query_shapes(
    team_id: int,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    shape_limit: int = DEFAULT_SHAPE_LIMIT,
) -> list[QueryShape]:
    # Tagging is required on every ClickHouse call. It also keeps the scan out of its own results,
    # because `_EXCLUDED_PRODUCTS` drops data_catalog traffic on the next run.
    tag_queries(product=Product.DATA_CATALOG, feature=Feature.QUERY)
    rows = sync_execute(
        _QUERY_SHAPES_SQL,
        {
            "team_id": team_id,
            "lookback_days": lookback_days,
            "shape_limit": shape_limit,
            "excluded_products": _EXCLUDED_PRODUCTS,
            "max_users": _MAX_TRACKED_USERS_PER_SHAPE,
        },
        team_id=team_id,
    )
    return [
        QueryShape(
            sample_hogql=sample_hogql,
            user_ids=frozenset(user_ids),
            active_days=frozenset(str(day) for day in active_days),
            runs=runs,
        )
        for sample_hogql, user_ids, active_days, runs in rows
    ]


def fold_shapes(
    shapes: list[QueryShape],
    *,
    min_distinct_users: int = DEFAULT_MIN_DISTINCT_USERS,
) -> DiscoveryScan:
    """Group query shapes onto the measures they compute, then keep the ones above the bar.

    User sets are unioned rather than added. The same people run several shapes of one measure, so
    adding per-shape counts would report an audience the measure does not have.
    """
    accumulators: dict[str, _Accumulator] = {}
    unparsed = 0
    without_aggregate = 0

    for shape in shapes:
        try:
            measures = extract_measures(shape.sample_hogql)
        except MeasureExtractionError:
            unparsed += 1
            continue

        if not measures:
            without_aggregate += 1
            continue

        for measure in measures:
            _absorb(accumulators, measure, shape)

    candidates = [
        MetricCandidate(
            fingerprint=accumulator.fingerprint,
            user_ids=frozenset(accumulator.user_ids),
            active_days=frozenset(accumulator.active_days),
            runs=accumulator.runs,
            shape_count=accumulator.shape_count,
        )
        for accumulator in accumulators.values()
    ]
    above_bar = [candidate for candidate in candidates if candidate.distinct_users >= min_distinct_users]

    return DiscoveryScan(
        candidates=tuple(sorted(above_bar, key=_rank, reverse=True)),
        shapes_read=len(shapes),
        shapes_unparsed=unparsed,
        shapes_without_aggregate=without_aggregate,
        measures_below_bar=len(candidates) - len(above_bar),
    )


def _absorb(accumulators: dict[str, _Accumulator], measure: MeasureFingerprint, shape: QueryShape) -> None:
    accumulator = accumulators.get(measure.digest)
    if accumulator is None:
        accumulators[measure.digest] = _Accumulator(
            fingerprint=measure,
            user_ids=set(shape.user_ids),
            active_days=set(shape.active_days),
            runs=shape.runs,
            shape_count=1,
        )
        return

    accumulator.user_ids.update(shape.user_ids)
    accumulator.active_days.update(shape.active_days)
    accumulator.runs += shape.runs
    accumulator.shape_count += 1


def _rank(candidate: MetricCandidate) -> tuple[int, int, int, str]:
    # The digest breaks ties so a scan of unchanged data returns the same order every time.
    return (candidate.distinct_users, candidate.distinct_days, candidate.runs, candidate.fingerprint.digest)
