"""
Labeling: build (user, T0, label) triples for horizon-based prediction.

Single source of truth for "what does a training example look like?" Used by
the wizard's live estimate (sampled), the trainer (full materialization with
fold split), and inference (per-user cutoff = now). The three call sites share
this module so they cannot drift apart — the wizard previews the same labels
the trainer will actually see, and inference scores against the same cutoff
contract the feature SQL was trained against.

Strategy: random T0 per user (deterministic hash of person_id), one row per
user. Each user is sampled at a single point in their history; label = whether
the target event fires in [T0, T0 + horizon_days). Random T0 (rather than
most-recent-feasible) keeps T0s spread across the full lookback so the model
generalises across time, not just the trailing horizon window.

Every T0 falls on a UTC midnight, and the anchor every training window ends at is
snapped to one, because every scoring run cuts off at the start of the prediction
date in UTC. A T0 at a random second would show the features part-day activity and
a cutoff hour that scoring never has, so the holdout score would not predict the
scoring score.

Per-user T0 cascades through the rest of the ML pipeline:
- Feature SQL must read events with `timestamp < cutoff_ts` per user, where
  cutoff_ts comes from a joined anchors table (the labeled_anchors CTE at
  training time, build_inference_anchors_sql at scoring time).
- Holdout split is by user (fold = hash(person_id) % 5) so the same person
  never appears in both train and holdout.
- Inference re-uses the same feature SQL with anchors = (person_id, cutoff), where
  a scoring run's cutoff is the start of the prediction date in UTC.

Integer handling notes:
- toUnixTimestamp returns UInt32; we cast to Int64 via toInt so subtractions
  and modulo work in signed space (HogQL exposes toInt → Int64; toUInt* is
  unsupported).
- cityHash64 returns UInt64. Casting directly to Int64 can flip sign when the
  high bit is set, which would place T0 before first_ts. Truncating to the
  lower 31 bits via bitAnd guarantees a non-negative hash without harming
  uniformity, and the position arithmetic stays inside Int64.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.property import action_to_expr

from posthog.dataclasses import frozen

from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Number of folds for hash-based train/holdout split. fold == 0 → holdout (20%).
NUM_FOLDS = 5

# Kinds whose membership is defined by the pipeline's own target rather than by a named event.
TARGET_RELATIVE_KINDS = frozenset({"active_not_performed_target", "ever_performed_target"})

# v1 scope: autoresearch models identified users only. Identified persons carry a
# stable real distinct_id, so scoring-time identity resolution always succeeds and the
# prediction event + output person property land on the right person — no phantom,
# person-less, or v5↔v7 edge cases. Anonymous / pre-signup populations (e.g.
# anonymous → signup) are deferred to v2. This is a hard limit baked into every
# population query; flip to False to relax — the rest of the pipeline is
# population-agnostic.
IDENTIFIED_USERS_ONLY = True

SECONDS_PER_DAY = 86400

# Models record this in metrics["anchor_alignment"]. A champion without it trained on
# T0s at any second, so its holdout score is not comparable with a model trained here.
ANCHOR_ALIGNMENT = "utc_day"

# The start of the current UTC day, without a timezone-aware function that HogQL could
# resolve in the project timezone.
_UTC_DAY_START_OF_NOW = "fromUnixTimestamp(intDiv(toInt(toUnixTimestamp(now())), 86400) * 86400)"

# The builders here read identity and person properties from `raw_persons` (see
# `_person_rows_sql`), never from `person.*` on an events scan, so these modifiers join no
# persons table into them. They pin how `person_id` resolves, so the anchors and the agent's
# feature SQL agree on it whatever mode the team is on, and a `person.*` column in feature
# SQL resolves through the persons table. Every caller that executes SQL from this module
# must pass them.
LABELER_QUERY_MODIFIERS = HogQLQueryModifiers(
    personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED
)


def utc_day_start(ts: int) -> int:
    """The UTC midnight at or before ``ts`` (unix seconds)."""
    return ts - ts % SECONDS_PER_DAY


def _identified_users_and_clause() -> str:
    """`AND person.is_identified` fragment for an events-table WHERE, or '' when the
    v1 identified-only scope is disabled. The events table must be unaliased at the
    call site (or aliased so that ``person`` still resolves via the lazy join)."""
    return " AND person.is_identified" if IDENTIFIED_USERS_ONLY else ""


# The product's own output event. Every live cadence writes one per scored person, so an
# activity scan that counted it would keep a person eligible forever on nothing but their
# own predictions, and would count the prediction as the first or last thing they did.
PREDICTION_EVENT_NAME = "autoresearch_prediction"


def _own_events_excluded_clause(alias: str = "") -> str:
    """`AND event != '<prediction event>'` fragment for an events-table WHERE; pass ``"e."`` for an aliased scan."""
    return f" AND {alias}event != '{PREDICTION_EVENT_NAME}'"


# The most persons one training or scoring run materializes. HogQL otherwise caps a query at its
# default of 100 rows; the materializers fail a result that fills this bound, and validation
# refuses a larger training population before a run is spent on it. A larger scoring population
# scores on a rolling basis instead (ROLLING_SCORE_LIMIT).
MATERIALIZE_ROW_LIMIT = 50_000

# The share of MATERIALIZE_ROW_LIMIT a sampled training population aims at. The rate is chosen
# from one count and applied in a later query, so the population can grow in between.
TRAINING_SAMPLE_HEADROOM = 0.8
TRAINING_SAMPLE_BUDGET = int(MATERIALIZE_ROW_LIMIT * TRAINING_SAMPLE_HEADROOM)

# Negative anchors are kept when the low 31 bits of this salted hash fall under the rate's
# threshold. The salt keeps the draw independent of the T0 and fold hashes of the same person.
_SAMPLE_HASH = "bitAnd(cityHash64(concat('sample:', toString(person_id))), 2147483647)"
_HASH_RANGE = 2147483648


class TrainingSampleTooLarge(ValueError):
    """The positives alone do not fit the training budget, so no negative sample rate can help."""


@frozen
class TrainingSample:
    """
    The case-control sample of training anchors: every positive, and each negative with
    probability ``negative_sample_rate``. A rate of 1.0 keeps the whole population.
    """

    population: int
    positives: int
    negative_sample_rate: float

    @property
    def negatives(self) -> int:
        return self.population - self.positives

    @property
    def expected_size(self) -> int:
        return self.positives + round(self.negatives * self.negative_sample_rate)

    @classmethod
    def plan(cls, *, population: int, positives: int, budget: int = TRAINING_SAMPLE_BUDGET) -> "TrainingSample":
        """
        Keep every anchor when the population fits ``budget``. Otherwise keep every positive and
        the fraction of negatives that fills the rest of it.
        """
        negatives = population - positives
        if population <= budget or negatives <= 0:
            return cls(population=population, positives=positives, negative_sample_rate=1.0)
        if positives >= budget:
            raise TrainingSampleTooLarge(
                f"The training population has {positives} positive examples, more than the {budget} that one "
                "run trains on. Narrow the population or shorten the horizon."
            )
        return cls(population=population, positives=positives, negative_sample_rate=(budget - positives) / negatives)


def negative_sample_threshold(negative_sample_rate: float) -> int:
    """The bound on the salted 31-bit hash under which a negative anchor is kept."""
    if not 0.0 < negative_sample_rate <= 1.0:
        raise ValueError(f"negative_sample_rate must be in (0, 1], got {negative_sample_rate!r}")
    return math.floor(negative_sample_rate * _HASH_RANGE)


# The most persons one scoring run scores when its population reaches MATERIALIZE_ROW_LIMIT. The
# run takes the people whose last score is oldest, so consecutive runs cycle through the whole
# population. The headroom keeps a materialized result clear of the truncation check.
ROLLING_SCORE_LIMIT = MATERIALIZE_ROW_LIMIT * 9 // 10

# The shortest window a rolling selection reads the pipeline's own predictions over. A larger
# population gets a longer window, see `rolling_selection()`.
ROLLING_SCORE_MIN_LOOKBACK_DAYS = 30


def rolling_score_limit(eligible: int) -> int | None:
    """The rolling selection size for a scoring population of ``eligible`` persons, or None when it scores whole."""
    return ROLLING_SCORE_LIMIT if eligible >= MATERIALIZE_ROW_LIMIT else None


def rolling_rescore_runs(*, eligible: int, scored: int) -> int:
    """How many scoring runs a rolling selection of ``scored`` persons takes to cover ``eligible`` persons."""
    return max(1, -(-eligible // max(scored, 1)))


@frozen
class RollingSelection:
    """The subset one scoring run takes from a population at or above the cap."""

    pipeline_id: str
    limit: int
    # How far back the ranking reads the pipeline's own predictions. A person scored before the
    # window ranks with the never-scored, so the window covers a whole cycle with room to grow.
    scored_lookback_days: int


def rolling_selection(*, eligible: int, pipeline_id: str, cadence_days: int) -> RollingSelection | None:
    """
    The rolling subset for a scoring population of ``eligible`` persons, or None when it scores whole.
    ``cadence_days`` is the pipeline's days between runs, so the history window covers a cycle in days.
    """
    limit = rolling_score_limit(eligible)
    if limit is None:
        return None
    cycle_days = rolling_rescore_runs(eligible=eligible, scored=limit) * max(cadence_days, 1)
    return RollingSelection(
        pipeline_id=pipeline_id,
        limit=limit,
        scored_lookback_days=max(ROLLING_SCORE_MIN_LOOKBACK_DAYS, 2 * cycle_days),
    )


@dataclass(frozen=True, kw_only=True)
class _CompiledPopulationFilters:
    # Person-property fragments on `raw_persons` columns, decided on each person's latest version.
    person_parts: list[str] = field(default_factory=list)
    # Event-property fragments, kept apart because training decides them per user at T0.
    event_parts: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)


def _numeric_threshold(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@frozen
class _CompiledFilter:
    """One compiled property filter. ``condition`` is None when the filter constrains nothing."""

    condition: str | None
    values: dict[str, Any] = field(default_factory=dict)


# `IN ()` is not valid HogQL, so an empty allowlist needs a predicate that matches nobody.
_MATCHES_NOBODY = "1 = 0"

# Scalar comparison, and the list form, per operator.
_MEMBERSHIP_SQL = {"exact": ("=", "IN"), "is_not": ("!=", "NOT IN")}
_COMPARISON_SQL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
# The LIKE operator, and how a list of patterns joins.
_SUBSTRING_SQL = {"icontains": ("ILIKE", " OR "), "not_icontains": ("NOT ILIKE", " AND ")}


def _membership_filter(field_expr: str, operator: str, value: Any, *, param: str) -> _CompiledFilter:
    """A list operand means IN / NOT IN. An empty denylist excludes nobody, so it drops out."""
    comparison, membership = _MEMBERSHIP_SQL[operator]
    if not isinstance(value, list):
        return _CompiledFilter(condition=f"{field_expr} {comparison} {{{param}}}", values={param: value})
    if not value:
        return _CompiledFilter(condition=_MATCHES_NOBODY if operator == "exact" else None)
    values = {f"{param}_{j}": v for j, v in enumerate(value)}
    refs = ", ".join(f"{{{name}}}" for name in values)
    return _CompiledFilter(condition=f"{field_expr} {membership} ({refs})", values=values)


def _substring_filter(field_expr: str, operator: str, value: Any, *, param: str) -> _CompiledFilter:
    """A list operand matches any of its values, or none of them for the negative operator."""
    patterns = value if isinstance(value, list) else [value]
    if not patterns:
        return _CompiledFilter(condition=_MATCHES_NOBODY if operator == "icontains" else None)
    like, joiner = _SUBSTRING_SQL[operator]
    values = {f"{param}_{j}": f"%{v}%" for j, v in enumerate(patterns)}
    clauses = joiner.join(f"{field_expr} {like} {{{name}}}" for name in values)
    return _CompiledFilter(condition=f"({clauses})" if len(patterns) > 1 else clauses, values=values)


def _comparison_filter(field_expr: str, operator: str, value: Any, *, key: str, param: str) -> _CompiledFilter:
    # The property side is cast to Float64, so the bound must be numeric too or ClickHouse
    # rejects the comparison. Filter payloads often carry it as a string.
    threshold = _numeric_threshold(value)
    if threshold is None:
        raise ValueError(f"Population property filter '{key}' needs a numeric value for '{operator}'")
    return _CompiledFilter(
        condition=f"toFloat64OrNull({field_expr}) {_COMPARISON_SQL[operator]} {{{param}}}",
        values={param: threshold},
    )


def _compile_filter_operator(field_expr: str, operator: str, value: Any, *, key: str, param: str) -> _CompiledFilter:
    """
    Compile one property filter's operator into a HogQL condition on ``field_expr``.

    ``is_set`` means not null, as in the canonical property compiler, so an empty
    string is a set value.
    """
    if operator == "is_set":
        return _CompiledFilter(condition=f"isNotNull({field_expr})")
    if operator == "is_not_set":
        return _CompiledFilter(condition=f"isNull({field_expr})")
    if operator in _MEMBERSHIP_SQL:
        return _membership_filter(field_expr, operator, value, param=param)
    if operator in _SUBSTRING_SQL:
        return _substring_filter(field_expr, operator, value, param=param)
    if operator in _COMPARISON_SQL:
        return _comparison_filter(field_expr, operator, value, key=key, param=param)
    raise ValueError(f"Unsupported population property operator '{operator}'")


def _compile_population_filters(properties: list[dict[str, Any]]) -> _CompiledPopulationFilters:
    """
    Translate a list of PostHog property filter dicts into HogQL condition
    strings and a values dict for parameterized binding.

    Property types:
    - "person"  → properties[<key>]  (raw_persons context, see ``_person_rows_sql``)
    - "event"   → properties[<key>]  (events table context)

    Operators: exact, is_not, icontains, not_icontains, gt, gte, lt, lte,
               is_set, is_not_set.

    The property key is bound as a HogQL value (a parameterized subscript,
    ``properties[{param}]``) rather than interpolated into the query text, so any
    key — including PostHog system properties like ``$browser`` — is safe without
    an allowlist. A filter that cannot be compiled (a cohort filter, an unknown
    operator, a missing key or type, a non-numeric threshold) raises ValueError:
    skipping it would silently widen the population, and inference writes person
    properties for everyone it scores. ``type`` has no default because the
    canonical compiler defaults it to ``event`` while this compiler's callers
    mostly mean ``person``; a filter that says neither is ambiguous.
    """
    person_parts: list[str] = []
    event_parts: list[str] = []
    values: dict[str, Any] = {}

    for i, prop in enumerate(properties):
        key = prop.get("key")
        prop_type = prop.get("type")

        if not key:
            raise ValueError("Population property filter is missing a 'key'")
        key = str(key)
        if not prop_type:
            raise ValueError(f"Population property filter '{key}' is missing a 'type'. Supported: event, person")

        if prop_type == "person":
            parts = person_parts
        elif prop_type == "event":
            parts = event_parts
        else:
            raise ValueError(f"Unsupported population property type '{prop_type}'. Supported: event, person")

        operator = prop.get("operator", "exact")
        if not isinstance(operator, str):
            # The operator tables below are dicts, so an unhashable operator would raise
            # TypeError before it reached the unsupported-operator path.
            raise ValueError(f"Unsupported population property operator '{operator}'")

        # Bind the key as a value (parameterized subscript) — never interpolate it into SQL text.
        key_param = f"pop_k_{i}"
        values[key_param] = key

        compiled = _compile_filter_operator(
            f"properties[{{{key_param}}}]",
            operator,
            prop.get("value"),
            key=key,
            param=f"pop_{i}",
        )
        values.update(compiled.values)
        if compiled.condition is not None:
            parts.append(compiled.condition)

    return _CompiledPopulationFilters(person_parts=person_parts, event_parts=event_parts, values=values)


def _person_rows_sql(
    members_sql: str,
    person_parts: list[str],
    *,
    select: str = "id",
    identified_only: bool = IDENTIFIED_USERS_ONLY,
) -> str:
    """
    One row per live person among ``members_sql``, read from ``raw_persons``.

    The ``id IN`` filter sits inside the version dedupe, so ClickHouse reads only the
    members' rows through the person sort key. The HogQL ``persons`` table dedupes every
    person of the team before any filter applies. Each person condition is evaluated on
    every version and ``argMax`` keeps the latest version's result. ``ifNull`` reads a NULL
    result (a missing property) as false, as an events-scan WHERE does.
    """
    having = ["argMax(is_deleted, version) = 0"]
    if identified_only:
        having.append("argMax(is_identified, version) = 1")
    having.extend(f"argMax(ifNull(({part}), 0), version) = 1" for part in person_parts)
    return f"SELECT {select} FROM raw_persons WHERE id IN ({members_sql}) GROUP BY id HAVING {' AND '.join(having)}"


# Anchor-mode predicates run inside the labeled_users CTE, where the events scan is aliased
# ``e`` and each user's T0 comes from the joined ``u`` row.
_EVENT_TS = "toInt(toUnixTimestamp(e.timestamp))"
_T0 = "u.t0_ts"


@dataclass(frozen=True, kw_only=True)
class _CompiledPopulationKind:
    where_parts: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    # Training-only predicates applied per user at T0 in the labeled_users HAVING clause.
    anchor_having_parts: list[str] = field(default_factory=list)
    # Row-mode conditions on `raw_persons` columns, applied by `_person_rows_sql`.
    person_parts: list[str] = field(default_factory=list)
    # The row predicate that every member event matches. When set, the member scans read only
    # these events, which the events sort key prunes. None means membership needs any event.
    member_predicate: str | None = None


def _members_within(instant: str, days_param: str, *, predicate: str = "", negate: bool = False) -> str:
    """Row filter: users with an event matching ``predicate`` in the ``days_param``-day window ending at ``instant``."""
    membership = "NOT IN" if negate else "IN"
    return (
        f"person_id {membership} (SELECT DISTINCT person_id FROM events"
        f" WHERE timestamp >= {instant} - toIntervalDay({{{days_param}}})"
        f" AND timestamp < {instant}{_own_events_excluded_clause()}{predicate})"
    )


def _performed_before_t0(predicate: str, *, days_param: str | None = None) -> str:
    """Per-user aggregate: 1 when an event matching ``predicate`` precedes T0, within ``days_param`` days of it if given."""
    window = f"{_EVENT_TS} < {_T0}"
    if days_param is not None:
        window = f"{_EVENT_TS} >= {_T0} - {{{days_param}}} * 86400 AND {window}"
    return f"max(({window}{predicate}))"


@frozen
class _PopulationKindSpec:
    """One semantic population spec, plus the mode and target predicate it compiles against."""

    kind: str
    raw: dict[str, Any]
    now_expr: str
    anchor_mode: bool
    target_cond: str | None

    def positive_int(self, key: str) -> int:
        value = self.raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Population kind '{self.kind}' requires a positive integer '{key}'")
        return value

    def event_clause(self) -> tuple[str, dict[str, Any]]:
        """The scan predicate for the spec's named event, and the value it binds."""
        value = self.raw.get("event")
        if not value or not isinstance(value, str):
            raise ValueError(f"Population kind '{self.kind}' requires an 'event'")
        return " AND event = {popk_event}", {"popk_event": value}

    def optional_event_clause(self) -> tuple[str, dict[str, Any]]:
        """``event_clause`` for a kind whose event is optional, where naming none narrows nothing."""
        if not self.raw.get("event"):
            return "", {}
        return self.event_clause()

    def target_clause(self) -> str:
        if self.target_cond is None:
            raise ValueError(f"Population kind '{self.kind}' requires the pipeline's target predicate")
        return f" AND ({self.target_cond})"


def _kind_performed_event_within_days(spec: _PopulationKindSpec) -> _CompiledPopulationKind:
    values: dict[str, Any] = {"popk_days": spec.positive_int("days")}
    event_clause, event_values = spec.optional_event_clause()
    values.update(event_values)
    member_predicate = "event = {popk_event}" if event_clause else None
    if not spec.anchor_mode:
        return _CompiledPopulationKind(
            where_parts=[_members_within(spec.now_expr, "popk_days", predicate=event_clause)],
            values=values,
            member_predicate=member_predicate,
        )
    return _CompiledPopulationKind(
        # A cheap superset that bounds the scan; the HAVING decides membership at each user's T0.
        where_parts=[_members_within(spec.now_expr, "lookback", predicate=event_clause)] if event_clause else [],
        values=values,
        anchor_having_parts=[f"{_performed_before_t0(event_clause, days_param='popk_days')} = 1"],
        member_predicate=member_predicate,
    )


def _kind_person_first_seen_within_days(spec: _PopulationKindSpec) -> _CompiledPopulationKind:
    values: dict[str, Any] = {"popk_days": spec.positive_int("days")}
    # Deliberately not bounded above by the anchor: an imported or backdated event stream
    # carries person rows created after their events, and an upper bound would empty the
    # training population for exactly those teams.
    if spec.anchor_mode:
        return _CompiledPopulationKind(
            values=values,
            anchor_having_parts=[f"min(u.person_created_ts) >= {_T0} - {{popk_days}} * 86400"],
        )
    return _CompiledPopulationKind(
        person_parts=[f"created_at >= {spec.now_expr} - toIntervalDay({{popk_days}})"],
        values=values,
    )


def _kind_active_not_performed_target(spec: _PopulationKindSpec) -> _CompiledPopulationKind:
    values: dict[str, Any] = {"popk_active_days": spec.positive_int("active_within_days")}
    target_clause = spec.target_clause()
    if spec.anchor_mode:
        return _CompiledPopulationKind(
            values=values,
            anchor_having_parts=[
                f"{_performed_before_t0('', days_param='popk_active_days')} = 1",
                # A property-filtered action predicate is NULL on rows missing the property. max()
                # skips NULLs, so a user whose every pre-T0 row is NULL would compare NULL = 0 and
                # drop out, while the row-mode NOT IN keeps them. Read that NULL as "not performed".
                f"ifNull({_performed_before_t0(target_clause)}, 0) = 0",
            ],
        )
    return _CompiledPopulationKind(
        where_parts=[
            _members_within(spec.now_expr, "popk_active_days"),
            _members_within(spec.now_expr, "lookback", predicate=target_clause, negate=True),
        ],
        values=values,
    )


def _kind_ever_performed_event(spec: _PopulationKindSpec) -> _CompiledPopulationKind:
    event_clause, values = spec.event_clause()
    # In anchor mode the row filter is a cheap superset (performed within the lookback as of
    # now); the HAVING narrows it to "performed before this user's T0".
    return _CompiledPopulationKind(
        where_parts=[_members_within(spec.now_expr, "lookback", predicate=event_clause)],
        values=values,
        anchor_having_parts=[f"{_performed_before_t0(event_clause)} = 1"] if spec.anchor_mode else [],
        member_predicate="event = {popk_event}",
    )


def _kind_ever_performed_target(spec: _PopulationKindSpec) -> _CompiledPopulationKind:
    target_clause = spec.target_clause()
    return _CompiledPopulationKind(
        where_parts=[_members_within(spec.now_expr, "lookback", predicate=target_clause)],
        anchor_having_parts=[f"{_performed_before_t0(target_clause)} = 1"] if spec.anchor_mode else [],
        member_predicate=f"({spec.target_cond})",
    )


# The registry of semantic population kinds produced by templates.py, and the single source of
# truth for POPULATION_KINDS. The write-time validator in presentation/views/serializers.py
# rejects any kind missing from it, so a kind cannot reach query time without a compiler.
_POPULATION_KIND_COMPILERS: dict[str, Callable[[_PopulationKindSpec], _CompiledPopulationKind]] = {
    "performed_event_within_days": _kind_performed_event_within_days,
    "person_first_seen_within_days": _kind_person_first_seen_within_days,
    "active_not_performed_target": _kind_active_not_performed_target,
    "ever_performed_event": _kind_ever_performed_event,
    "ever_performed_target": _kind_ever_performed_target,
}

POPULATION_KINDS = frozenset(_POPULATION_KIND_COMPILERS)


def _build_population_kind_conditions(
    population: dict[str, Any] | None,
    *,
    now_expr: str = "now()",
    anchor_mode: bool = False,
    target_cond: str | None = None,
) -> _CompiledPopulationKind:
    """
    Compile a semantic population spec (``{"kind": ..., ...}``, produced by
    templates.py) into HogQL fragments for an events scan.

    Membership subqueries are bounded to the caller's lookback window, so
    "ever performed" and "has not performed" mean "within the lookback window" —
    the scan cost stays proportional to the data the query already reads. The
    emitted fragments reference the ``{lookback}`` bound value, which every
    population-consuming builder in this module binds.

    ``now_expr`` is the anchor instant — ``now()`` for live queries, or a bound
    backfill cutoff expression for historical scoring. Row-mode windows are
    computed relative to it.

    ``anchor_mode=True`` (training) decides membership per user at that user's
    own T0 instead of at ``now_expr``: the tests move from ``where_parts`` into
    ``anchor_having_parts``, which ``_build_labeled_users_cte`` applies against
    each user's anchor, exactly as inference decides them as of its cutoff.
    Deciding training membership as of now() would admit users on activity after
    T0 (including the outcome window), and a row-level "has not performed the
    target" filter would delete exactly the users whose post-T0 adoption provides
    the positive labels. Where a cheap superset exists it stays in ``where_parts``
    to bound the scan.

    ``target_cond`` is the predicate from ``build_target_condition``. The
    target-relative kinds require it, so an action target is matched by its
    compiled matcher rather than by its display name.

    Raises ValueError on an unknown kind or a spec missing a required key — a
    population that cannot be compiled must fail loudly rather than silently
    widening to "all users".
    """
    raw = population or {}
    kind = raw.get("kind")
    if kind is None:
        return _CompiledPopulationKind()
    compiler = _POPULATION_KIND_COMPILERS.get(kind)
    if compiler is None:
        raise ValueError(f"Unknown population kind '{kind}'. Supported: {', '.join(sorted(POPULATION_KINDS))}")
    return compiler(
        _PopulationKindSpec(
            kind=kind,
            raw=raw,
            now_expr=now_expr,
            anchor_mode=anchor_mode,
            target_cond=target_cond,
        )
    )


def _member_clause(compiled_filters: _CompiledPopulationFilters, compiled_kind: _CompiledPopulationKind) -> str:
    """
    ``AND (<member predicate>)`` fragment that narrows a member scan to the population's
    own event, or '' when membership needs any event.

    An event-property filter can match any event, so it keeps the any-event scan.
    """
    if compiled_kind.member_predicate is None or compiled_filters.event_parts:
        return ""
    return f" AND ({compiled_kind.member_predicate})"


def _target_condition_for(
    population: dict[str, Any] | None,
    *,
    target_event: str,
    target_definition: dict[str, Any] | None,
    team: "Team | None",
) -> tuple[str | None, dict[str, Any]]:
    """The compiled target predicate when ``population`` is target-relative, else nothing.

    Resolving an action target reads the Action row, so callers that only need a
    row-mode population do not pay for it unless a kind consumes it.
    """
    if (population or {}).get("kind") not in TARGET_RELATIVE_KINDS:
        return None, {}
    return build_target_condition(target_event=target_event, target_definition=target_definition, team=team)


def build_target_condition(
    *,
    target_event: str,
    target_definition: dict[str, Any] | None,
    team: "Team | None",
) -> tuple[str, dict[str, Any]]:
    """
    Build the HogQL boolean fragment deciding whether a single events-table row
    matches the prediction target, plus any bound parameter values.

    The target is the only place an event target and an action target differ —
    features, scoring, and inference are all target-agnostic. Two shapes:
      - event target  → ``event = {target}`` (one bound value).
      - action target → the action's matcher compiled via ``action_to_expr`` and
        printed back to a self-contained HogQL fragment. The printer inlines and
        escapes constants, so the action path needs no extra bound values.

    ``target_definition`` selects the shape: ``{"type": "action", "action_id": N}``
    routes to the action path; anything else (empty, the default, or
    ``{"type": "event"}``) uses ``target_event``.

    The compiled fragment references events-table columns unqualified (``event``,
    ``properties``, ``elements_chain``). Every call site embeds it where those
    columns resolve to the events table — the labeler join (``events e`` plus a
    person-keyed anchors table that exposes none of them) and the realized-label
    query (``FROM events``) — so the absent table alias is intentional and safe.
    """
    definition = target_definition or {}
    if definition.get("type") == "action":
        action_id = definition.get("action_id")
        if action_id is None:
            raise ValueError("Action target requires 'action_id' in target_definition")
        if team is None:
            raise ValueError("Action target requires a team to resolve the action")
        # Scope the lookup to the pipeline's project so a foreign action id can't leak across
        # tenants. Actions live on the project's root team, so a team match would miss them
        # from any other environment of the same project.
        action = Action.objects.get(id=action_id, team__project_id=team.project_id, deleted=False)
        if not action.steps:
            # action_to_expr compiles an empty step list to a constant true, which would label
            # every event in the horizon a positive.
            raise ValueError(f"Action target {action_id} has no steps, so it matches no events")
        return f"({action_to_expr(action).to_hogql()})", {}
    return "event = {target}", {"target": target_event}


def _build_labeled_users_cte(
    *,
    target_event: str,
    target_definition: dict[str, Any] | None,
    team: "Team | None",
    horizon_days: int,
    lookback_days: int,
    training_population: dict[str, Any] | None,
    sample_limit: int | None,
    anchor_ts: int | None = None,
    negative_sample_rate: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """
    Build the WITH clause that materialises the labeled_users table:
        labeled_users(person_id, t0_ts, positive)
    Caller appends `SELECT ... FROM labeled_users` to use it.

    A ``negative_sample_rate`` below 1 keeps every positive and each negative whose salted
    person hash falls under the rate, so the same people are drawn on every run. At 1.0 the
    query is the unsampled one.

    Population membership is decided per user at T0. Person-property filters and
    identity come from ``raw_persons``, and the kinds' cheap superset fragments
    narrow the events scan; event-property filters and the semantic kinds are
    evaluated in the labeled_users HAVING against each user's own anchor, so the
    training population is the same one inference selects as of its cutoff.

    A kind with a member predicate (an event-defined population) reads only its
    own events for the T0 span, and only those plus the target for the labels.

    sample_limit caps user_window for fast wizard previews; None = full
    materialization (trainer).

    anchor_ts (unix seconds) sets the instant every window ends at; None = now().
    Either one is snapped to the UTC midnight at or before it, so the label cutoff
    (the anchor minus the horizon) and every T0 are UTC midnights, as the scoring
    cutoff is. Queries that must agree on the anchor set, such as the training
    features and the anchor count, bind the same anchor_ts, because each query reads
    its own now() and a person at a window edge can fall in one and not the other.
    """
    training_properties = (training_population or {}).get("properties", []) if training_population else []
    compiled_filters = _compile_population_filters(training_properties)
    target_cond, target_values = build_target_condition(
        target_event=target_event, target_definition=target_definition, team=team
    )
    now_expr = "fromUnixTimestamp({anchor_ts})" if anchor_ts is not None else _UTC_DAY_START_OF_NOW
    compiled_kind = _build_population_kind_conditions(
        training_population, now_expr=now_expr, anchor_mode=True, target_cond=target_cond
    )
    member_clause = _member_clause(compiled_filters, compiled_kind)
    superset_clause = f" AND ({' AND '.join(compiled_kind.where_parts)})" if compiled_kind.where_parts else ""
    member_scan = (
        f"timestamp >= {now_expr} - toIntervalDay({{lookback}})"
        f" AND timestamp < {now_expr}{_own_events_excluded_clause()}{member_clause}{superset_clause}"
    )
    persons_sql = _person_rows_sql(
        f"SELECT person_id FROM events WHERE {member_scan}",
        compiled_filters.person_parts,
        select="id, toInt(toUnixTimestamp(argMax(created_at, version))) AS created_ts",
    )
    # With a member predicate, the label scan reads only the target and the population event:
    # the HAVING below needs no other rows. Without one, membership at T0 can need any event.
    label_scan_clause = ""
    if member_clause:
        target_expr = f"({target_cond})"
        label_scan_clause = (
            f" AND {target_expr}"
            if compiled_kind.member_predicate == target_expr
            else f" AND ({target_expr} OR ({compiled_kind.member_predicate}))"
        )
    # A bare LIMIT would hand back whatever ClickHouse reads first, which correlates with
    # storage order; the sampled base rate is extrapolated to the whole population, so order
    # by a uniform hash of the person to make the sample representative and reproducible.
    limit_clause = (
        f"\n            ORDER BY cityHash64(toString(m.person_id))\n            LIMIT {int(sample_limit)}"
        if sample_limit is not None
        else ""
    )

    # One aggregate over the conjunction, not one per filter: inference ANDs the event
    # filters on a single row, so training must require one pre-T0 event that satisfies all.
    having_parts: list[str] = []
    if compiled_filters.event_parts:
        event_predicate = " AND ".join(compiled_filters.event_parts)
        having_parts.append(f"{_performed_before_t0(f' AND ({event_predicate})')} = 1")
    having_parts.extend(compiled_kind.anchor_having_parts)
    anchor_having = f"\n              HAVING {' AND '.join(having_parts)}" if having_parts else ""

    # A sampled population labels into labeled_population, and labeled_users keeps the sample of it.
    labeled_cte = "labeled_population" if negative_sample_rate < 1.0 else "labeled_users"

    # ifNull on the label: a property-filtered action predicate is NULL on rows that lack
    # the property, and a user whose every in-horizon row is NULL must label 0, not NULL.
    # T0 is the UTC midnight at a fixed fraction (hash / 2^31) of the midnights from the first
    # one after first_ts up to cutoff_ts, which is a midnight too. A `hash % span`
    # remainder would change every time cutoff_ts moved, handing the same person a different
    # T0, features, and label on each run. With a member predicate, first_ts is the user's
    # first population event, else their first event of any kind. A first event exactly at
    # midnight must not become T0, because the person would then have no event before T0.
    cte = f"""
        WITH user_window AS (
            SELECT
                m.person_id AS person_id,
                intDiv(m.first_ts, 86400) + 1 AS first_day,
                intDiv(m.cutoff_ts, 86400) AS cutoff_day,
                p.created_ts AS person_created_ts
            FROM (
                SELECT
                    person_id,
                    toInt(toUnixTimestamp(min(timestamp))) AS first_ts,
                    toInt(toUnixTimestamp({now_expr} - toIntervalDay({{horizon}}))) AS cutoff_ts
                FROM events
                WHERE {member_scan}
                GROUP BY person_id
                HAVING first_ts < cutoff_ts
            ) AS m
            INNER JOIN ({persons_sql}) AS p ON m.person_id = p.id{limit_clause}
        ),
        user_t0 AS (
            SELECT
                person_id,
                person_created_ts,
                (first_day
                  + intDiv((cutoff_day - first_day + 1) * toInt(bitAnd(cityHash64(toString(person_id)), 2147483647)), 2147483648)
                ) * 86400 AS t0_ts
            FROM user_window
        ),
        {labeled_cte} AS (
            SELECT
                u.person_id AS person_id,
                u.t0_ts AS t0_ts,
                ifNull(max(
                    {target_cond}
                    AND toInt(toUnixTimestamp(e.timestamp)) >= u.t0_ts
                    AND toInt(toUnixTimestamp(e.timestamp)) < u.t0_ts + ({{horizon}} * 86400)
                ), 0) AS positive
            FROM events e
            INNER JOIN user_t0 u ON e.person_id = u.person_id
            WHERE e.timestamp >= {now_expr} - toIntervalDay({{lookback}})
              AND e.timestamp < {now_expr}{_own_events_excluded_clause("e.")}{label_scan_clause}
            GROUP BY u.person_id, u.t0_ts{anchor_having}
        )
    """
    values: dict[str, Any] = {
        "horizon": horizon_days,
        "lookback": lookback_days,
        **target_values,
        **compiled_filters.values,
        **compiled_kind.values,
    }
    if anchor_ts is not None:
        values["anchor_ts"] = utc_day_start(anchor_ts)
    if negative_sample_rate < 1.0:
        values["negative_sample_threshold"] = negative_sample_threshold(negative_sample_rate)
        cte += f"""    ,
        labeled_users AS (
            SELECT person_id, t0_ts, positive
            FROM labeled_population
            WHERE positive = 1 OR {_SAMPLE_HASH} < {{negative_sample_threshold}}
        )
    """
    return cte, values


def build_random_t0_labeler_sql(
    *,
    target_event: str,
    horizon_days: int,
    lookback_days: int,
    training_population: dict[str, Any] | None,
    sample_limit: int | None = None,
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
    anchor_ts: int | None = None,
    negative_sample_rate: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """
    Build a HogQL query that returns one row of (eligible, positives) for a
    random-T0-per-user labeler. Used by the wizard for live base-rate feedback.

    eligible: users in the training_population with at least one event before
              now - horizon_days (so a horizon window fits in the data).
    positives: of those, users who fire target_event in [T0, T0 + horizon).

    With sample_limit=None this gives the trainer's actual eligible count;
    with sample_limit=N it gives an unbiased estimator computed over N users.
    With a ``negative_sample_rate`` it counts the case-control sample the trainer
    materializes at that rate.
    """
    cte, values = _build_labeled_users_cte(
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
        sample_limit=sample_limit,
        anchor_ts=anchor_ts,
        negative_sample_rate=negative_sample_rate,
    )
    sql = f"""
        {cte}
        SELECT
            count() AS eligible,
            sum(positive) AS positives
        FROM labeled_users
    """
    return sql, values


def build_eligible_count_sql(
    *,
    horizon_days: int,
    lookback_days: int,
    training_population: dict[str, Any] | None,
    target_event: str = "",
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
) -> tuple[str, dict[str, Any]]:
    """
    Build a HogQL query returning the count of users eligible to be labeled by the
    random-T0 labeler — i.e. users in the training_population with at least one member
    event (the population event, or any event when the population names none) before
    the start of the current UTC day minus horizon_days, the labeler's cutoff. Used as the UI headline number so the wizard reports
    the full population size, not the sampled subset.

    Returns two columns: ``eligible`` (the v1 headline — restricted to identified
    users when IDENTIFIED_USERS_ONLY is on) and ``eligible_all`` (the same count
    without the identified restriction). The caller divides the two to detect a
    mostly-anonymous population and warn that v1 excludes the anonymous remainder.
    """
    training_properties = (training_population or {}).get("properties", []) if training_population else []
    compiled_filters = _compile_population_filters(training_properties)
    # Row mode: the target-relative kinds are evaluated as of the day start here, which is an
    # approximation of the trainer's per-user-at-T0 semantics — acceptable for an
    # advisory headline count.
    target_cond, target_values = _target_condition_for(
        training_population, target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_kind = _build_population_kind_conditions(
        training_population, now_expr=_UTC_DAY_START_OF_NOW, target_cond=target_cond
    )
    row_parts = compiled_filters.event_parts + compiled_kind.where_parts
    row_clause = f" AND ({' AND '.join(row_parts)})" if row_parts else ""
    member_clause = _member_clause(compiled_filters, compiled_kind)

    # A member event before the day start minus the horizon is the trainer's `first_ts < cutoff_ts`.
    members_sql = (
        "SELECT person_id FROM events"
        f" WHERE timestamp >= {_UTC_DAY_START_OF_NOW} - toIntervalDay({{lookback}})"
        f" AND timestamp < {_UTC_DAY_START_OF_NOW} - toIntervalDay({{horizon}}){_own_events_excluded_clause()}{member_clause}{row_clause}"
    )
    persons_sql = _person_rows_sql(
        members_sql,
        compiled_filters.person_parts + compiled_kind.person_parts,
        select="id, argMax(is_identified, version) AS is_identified",
        identified_only=False,
    )
    eligible_expr = "countIf(is_identified = 1)" if IDENTIFIED_USERS_ONLY else "count()"

    sql = f"""
        SELECT
            {eligible_expr} AS eligible,
            count() AS eligible_all
        FROM ({persons_sql})
    """
    values: dict[str, Any] = {
        "horizon": horizon_days,
        "lookback": lookback_days,
        **target_values,
        **compiled_filters.values,
        **compiled_kind.values,
    }
    return sql, values


def build_inference_anchors_sql(
    *,
    lookback_days: int,
    inference_population: dict[str, Any] | None,
    cutoff_ts: int | None = None,
    target_event: str = "",
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
    rolling: RollingSelection | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Build a HogQL query producing (person_id, cutoff_ts) rows for scoring.

    cutoff_ts defaults to now() for every row — at inference time we score "the
    user's state as of right now." Pass an explicit ``cutoff_ts`` (unix seconds)
    to backfill a historical prediction date: features are then computed strictly
    before that instant, exactly as live scoring would have on that day. Eligible
    = users in inference_population with at least one member event (the population
    event, or any event when the population names none) in the lookback_days window
    before the cutoff. One row per person, read from ``raw_persons``.

    Substituted as the {anchors} table when running the agent's feature_sql
    at inference time. Same SQL the trainer executed against per-user T0;
    only the anchors table changes.

    ``rolling`` keeps only ``rolling.limit`` eligible persons: first the ones the pipeline never
    scored, then the oldest last score, then the most recent member event, then a hash of the
    person. Every key reads events before the cutoff, so a retry of the same prediction date
    selects the same people.
    """
    inference_properties = (inference_population or {}).get("properties", []) if inference_population else []
    compiled_filters = _compile_population_filters(inference_properties)

    # now() for live scoring; a bound, backdated instant for a historical backfill.
    cutoff_expr = "fromUnixTimestamp({cutoff_ts})" if cutoff_ts is not None else "now()"
    cutoff_select = "toInt({cutoff_ts})" if cutoff_ts is not None else "toInt(toUnixTimestamp(now()))"

    # Row mode anchored at the cutoff: population membership is decided as of the
    # scoring instant, mirroring how training decides it as of each user's T0.
    target_cond, target_values = _target_condition_for(
        inference_population, target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_kind = _build_population_kind_conditions(
        inference_population, now_expr=cutoff_expr, target_cond=target_cond
    )
    row_parts = compiled_filters.event_parts + compiled_kind.where_parts
    row_clause = f" AND ({' AND '.join(row_parts)})" if row_parts else ""
    member_clause = _member_clause(compiled_filters, compiled_kind)

    member_scan = (
        f"timestamp >= {cutoff_expr} - toIntervalDay({{lookback}})"
        f" AND timestamp < {cutoff_expr}{_own_events_excluded_clause()}{member_clause}{row_clause}"
    )
    sql = _person_rows_sql(
        f"SELECT person_id FROM events WHERE {member_scan}",
        compiled_filters.person_parts + compiled_kind.person_parts,
        select=f"id AS person_id, {cutoff_select} AS cutoff_ts",
    )
    values: dict[str, Any] = {
        "lookback": lookback_days,
        **target_values,
        **compiled_filters.values,
        **compiled_kind.values,
    }
    if cutoff_ts is not None:
        values["cutoff_ts"] = cutoff_ts
    if rolling is not None:
        # A live prediction attaches to the real person, so its person_id joins the anchor. A
        # backfill is person-less, so it does not count as a score that refreshed the person.
        sql = f"""
            SELECT a.person_id AS person_id, a.cutoff_ts AS cutoff_ts
            FROM ({sql}) AS a
            LEFT JOIN (
                SELECT person_id, toInt(toUnixTimestamp(max(timestamp))) AS last_scored_ts
                FROM events
                WHERE event = '{PREDICTION_EVENT_NAME}'
                  AND timestamp >= {cutoff_expr} - toIntervalDay({{rolling_scored_lookback}})
                  AND timestamp < {cutoff_expr}
                  AND properties.$autoresearch_pipeline_id = {{rolling_pipeline_id}}
                GROUP BY person_id
            ) AS s ON a.person_id = s.person_id
            LEFT JOIN (
                SELECT person_id, toInt(toUnixTimestamp(max(timestamp))) AS last_active_ts
                FROM events
                WHERE {member_scan}
                GROUP BY person_id
            ) AS m ON a.person_id = m.person_id
            ORDER BY
                ifNull(s.last_scored_ts, 0) ASC,
                ifNull(m.last_active_ts, 0) DESC,
                cityHash64(toString(a.person_id)) ASC,
                toString(a.person_id) ASC
            LIMIT {int(rolling.limit)}
        """
        values["rolling_scored_lookback"] = rolling.scored_lookback_days
        values["rolling_pipeline_id"] = rolling.pipeline_id
    return sql, values


_LINE_COMMENT_STARTS = ("--", "//")
_ANCHORS_PLACEHOLDER = "{anchors}"


def _literal_end(sql: str, start: int) -> int:
    """
    The index just past the closing quote of the literal that opens at ``start``.

    Honors both the doubled-quote and the backslash escape the HogQL lexer accepts.
    An unterminated literal runs to the end of the text, where the parser rejects it.
    """
    quote = sql[start]
    i = start + 1
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == quote:
            if i + 1 < n and sql[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _rewrite_outside_literals(sql: str, *, placeholder: str | None = None, replacement: str = "") -> str:
    """
    One quote-aware pass over HogQL text: drop ``--`` / ``//`` line comments and
    ``/* */`` block comments, and replace ``placeholder`` where it appears in code.

    Single-quoted strings, double-quoted and backtick identifiers are copied
    verbatim, so a comment marker or a placeholder inside a literal is left alone:
    the literal is a feature value, not a table reference.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        if sql[i] in ("'", '"', "`"):
            end = _literal_end(sql, i)
            out.append(sql[i:end])
            i = end
            continue
        if sql.startswith(_LINE_COMMENT_STARTS, i):
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            continue  # leave the newline so adjacent tokens don't fuse
        if sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            i = n if close < 0 else close + 2
            out.append(" ")  # block comment may sit mid-expression; keep a separator
            continue
        if placeholder and sql.startswith(placeholder, i):
            out.append(replacement)
            i += len(placeholder)
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def strip_sql_comments(sql: str) -> str:
    """
    Remove line and block comments from HogQL, leaving string/identifier literals intact.

    Agent-authored feature SQL routinely carries comments. Blindly substituting
    ``{anchors}`` with a multi-line subquery that happens to land inside a line
    comment injects newlines that escape the comment and corrupt the parse, and a
    comment can also swallow the rest of a line it was never meant to. Stripping
    comments before substitution sidesteps both.
    """
    return _rewrite_outside_literals(sql)


def _substitute_anchors(feature_sql: str, anchors_subquery: str) -> str:
    """
    Substitute the agent's `{anchors}` placeholder with the actual per-user
    cutoff subquery. The contract from Step B's static validator guarantees
    the placeholder is present.

    Comments are stripped in the same pass so a placeholder sitting in (or
    adjacent to) a comment can't break the substituted SQL, and a placeholder
    inside a literal is kept as the value it is. A trailing statement
    terminator is dropped because the training path nests the result as a
    derived table, where a ``;`` ends the statement early.
    """
    substituted = _rewrite_outside_literals(
        feature_sql, placeholder=_ANCHORS_PLACEHOLDER, replacement=anchors_subquery
    ).rstrip()
    return substituted[:-1] if substituted.endswith(";") else substituted


def build_training_features_sql(
    *,
    feature_sql: str,
    target_event: str,
    horizon_days: int,
    lookback_days: int,
    training_population: dict[str, Any] | None,
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
    anchor_ts: int | None = None,
    negative_sample_rate: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """
    Build the composite training-time query:
      labeled_users CTE  +  labeled_anchors (adds fold)
      + agent's feature_sql (with {anchors} substituted to per-user T0)
      + JOIN back to labels/fold so each feature row has (__label, __fold)

    Caller substitutes {lookback_days} in feature_sql before calling. Returns
    one row per eligible user with the agent's feature columns plus __label
    and __fold for the train/holdout split. A ``negative_sample_rate`` below 1
    restricts the rows to the case-control sample (see ``TrainingSample``).
    """
    cte, values = _build_labeled_users_cte(
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
        sample_limit=None,
        anchor_ts=anchor_ts,
        negative_sample_rate=negative_sample_rate,
    )
    anchors_subquery = "(SELECT person_id, t0_ts AS cutoff_ts FROM labeled_anchors)"
    substituted_feature_sql = _substitute_anchors(feature_sql, anchors_subquery)

    sql = f"""
        {cte},
        labeled_anchors AS (
            SELECT
                person_id,
                t0_ts,
                positive,
                toInt(bitAnd(cityHash64(concat('fold:', toString(person_id))), 2147483647)) % {NUM_FOLDS} AS fold
            FROM labeled_users
        )
        SELECT
            f.*,
            la.positive AS __label,
            la.fold AS __fold
        FROM (
            {substituted_feature_sql}
        ) f
        LEFT JOIN labeled_anchors la ON f.distinct_id = la.person_id
    """
    return sql, values


def build_inference_features_sql(
    *,
    feature_sql: str,
    lookback_days: int,
    inference_population: dict[str, Any] | None,
    cutoff_ts: int | None = None,
    target_event: str = "",
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
    rolling: RollingSelection | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Build the inference-time query: the agent's feature_sql with {anchors}
    substituted with the inference anchors (cutoff_ts = now() per user, or a
    backdated instant when ``cutoff_ts`` is given for a historical backfill).
    Returns one row per eligible scoring user with the agent's feature
    columns — no labels, no fold.

    Caller substitutes {lookback_days} in feature_sql before calling.
    ``rolling`` selects a rolling subset of the anchors, as in ``build_inference_anchors_sql``.
    """
    anchors_sql, anchors_values = build_inference_anchors_sql(
        lookback_days=lookback_days,
        inference_population=inference_population,
        cutoff_ts=cutoff_ts,
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        rolling=rolling,
    )
    # Wrap the inference anchors query as the {anchors} subquery — agent's
    # feature_sql references columns (person_id, cutoff_ts) just like training.
    anchors_subquery = f"({anchors_sql.strip()})"
    substituted_feature_sql = _substitute_anchors(feature_sql, anchors_subquery)
    return substituted_feature_sql, anchors_values
