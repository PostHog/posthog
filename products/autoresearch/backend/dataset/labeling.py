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

Per-user T0 cascades through the rest of the ML pipeline:
- Feature SQL must read events with `timestamp < cutoff_ts` per user, where
  cutoff_ts comes from a joined anchors table (the labeled_anchors CTE at
  training time, build_inference_anchors_sql at scoring time).
- Holdout split is by user (fold = hash(person_id) % 5) so the same person
  never appears in both train and holdout.
- Inference re-uses the same feature SQL with anchors = (person_id, now()).

Integer handling notes:
- toUnixTimestamp returns UInt32; we cast to Int64 via toInt so subtractions
  and modulo work in signed space (HogQL exposes toInt → Int64; toUInt* is
  unsupported).
- cityHash64 returns UInt64. Casting directly to Int64 can flip sign when the
  high bit is set, which would place T0 before first_ts. Truncating to the
  lower 31 bits via bitAnd guarantees a non-negative hash without harming
  uniformity, and the position arithmetic stays inside Int64.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from posthog.hogql.property import action_to_expr

from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

# Number of folds for hash-based train/holdout split. fold == 0 → holdout (20%).
NUM_FOLDS = 5

# Semantic population kinds produced by templates.py. Every kind listed here must have a
# compiler branch in _build_population_kind_conditions below — the write-time validator in
# presentation/views/serializers.py imports this set, so an uncompilable kind is rejected at creation.
POPULATION_KINDS = frozenset(
    {
        "performed_event_within_days",
        "person_first_seen_within_days",
        "active_not_performed_target",
        "ever_performed_event",
        "ever_performed_target",
    }
)

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


def _identified_users_and_clause() -> str:
    """`AND person.is_identified` fragment for an events-table WHERE, or '' when the
    v1 identified-only scope is disabled. The events table must be unaliased at the
    call site (or aliased so that ``person`` still resolves via the lazy join)."""
    return " AND person.is_identified" if IDENTIFIED_USERS_ONLY else ""


@dataclass(frozen=True, kw_only=True)
class _CompiledPopulationFilters:
    # Row-level fragments for an events scan whose ``person`` resolves through the lazy join.
    where_parts: list[str] = field(default_factory=list)
    # Event-property fragments, kept apart because training decides them per user at T0.
    event_parts: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)


def _compile_population_filters(properties: list[dict[str, Any]]) -> _CompiledPopulationFilters:
    """
    Translate a list of PostHog property filter dicts into HogQL condition
    strings and a values dict for parameterized binding.

    Property types:
    - "person"  → person.properties[<key>]  (events table context)
    - "event"   → properties[<key>]

    Operators: exact, is_not, icontains, not_icontains, gt, gte, lt, lte,
               is_set, is_not_set.

    The property key is bound as a HogQL value (a parameterized subscript,
    ``properties[{param}]``) rather than interpolated into the query text, so any
    key — including PostHog system properties like ``$browser`` — is safe without
    an allowlist. A filter that cannot be compiled (a cohort filter, an unknown
    operator, a missing key) raises ValueError: skipping it would silently widen
    the population, and inference writes person properties for everyone it scores.
    """
    person_parts: list[str] = []
    event_parts: list[str] = []
    values: dict[str, Any] = {}

    for i, prop in enumerate(properties):
        key = prop.get("key")
        prop_type = prop.get("type", "person")
        operator = prop.get("operator", "exact")
        value = prop.get("value")

        if not key:
            raise ValueError("Population property filter is missing a 'key'")

        if prop_type == "person":
            map_expr = "person.properties"
            parts = person_parts
        elif prop_type == "event":
            map_expr = "properties"
            parts = event_parts
        else:
            raise ValueError(f"Unsupported population property type '{prop_type}'. Supported: event, person")

        # Bind the key as a value (parameterized subscript) — never interpolate it into SQL text.
        key_param = f"pop_k_{i}"
        values[key_param] = str(key)
        field_expr = f"{map_expr}[{{{key_param}}}]"

        param = f"pop_{i}"

        if operator == "is_set":
            parts.append(f"isNotNull({field_expr}) AND {field_expr} != ''")
        elif operator == "is_not_set":
            parts.append(f"(isNull({field_expr}) OR {field_expr} = '')")
        elif operator in ("exact", "is_not") and isinstance(value, list):
            if not value:
                # `IN ()` is not valid HogQL. An empty allowlist matches nobody and an
                # empty denylist excludes nobody.
                if operator == "exact":
                    parts.append("1 = 0")
                continue
            for j, v in enumerate(value):
                values[f"pop_{i}_{j}"] = v
            in_refs = ", ".join(f"{{pop_{i}_{j}}}" for j in range(len(value)))
            membership = "IN" if operator == "exact" else "NOT IN"
            parts.append(f"{field_expr} {membership} ({in_refs})")
        elif operator == "exact":
            values[param] = value
            parts.append(f"{field_expr} = {{{param}}}")
        elif operator == "is_not":
            values[param] = value
            parts.append(f"{field_expr} != {{{param}}}")
        elif operator == "icontains":
            values[param] = f"%{value}%"
            parts.append(f"{field_expr} ILIKE {{{param}}}")
        elif operator == "not_icontains":
            values[param] = f"%{value}%"
            parts.append(f"{field_expr} NOT ILIKE {{{param}}}")
        elif operator in ("gt", "gte", "lt", "lte"):
            op_sql = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[operator]
            values[param] = value
            parts.append(f"toFloat64OrNull({field_expr}) {op_sql} {{{param}}}")
        else:
            raise ValueError(f"Unsupported population property operator '{operator}'")

    return _CompiledPopulationFilters(where_parts=person_parts, event_parts=event_parts, values=values)


def _build_population_conditions(
    properties: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Row-mode view of ``_compile_population_filters``: every filter applies to the scanned rows."""
    compiled = _compile_population_filters(properties)
    return compiled.where_parts + compiled.event_parts, compiled.values


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


def _members_within(instant: str, days_param: str, *, predicate: str = "", negate: bool = False) -> str:
    """Row filter: users with an event matching ``predicate`` in the ``days_param``-day window ending at ``instant``."""
    membership = "NOT IN" if negate else "IN"
    return (
        f"person_id {membership} (SELECT DISTINCT person_id FROM events"
        f" WHERE timestamp >= {instant} - toIntervalDay({{{days_param}}})"
        f" AND timestamp < {instant}{predicate})"
    )


def _performed_before_t0(predicate: str, *, days_param: str | None = None) -> str:
    """Per-user aggregate: 1 when an event matching ``predicate`` precedes T0, within ``days_param`` days of it if given."""
    window = f"{_EVENT_TS} < {_T0}"
    if days_param is not None:
        window = f"{_EVENT_TS} >= {_T0} - {{{days_param}}} * 86400 AND {window}"
    return f"max(({window}{predicate}))"


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
    spec = population or {}
    kind = spec.get("kind")
    if kind is None:
        return _CompiledPopulationKind()
    if kind not in POPULATION_KINDS:
        raise ValueError(f"Unknown population kind '{kind}'. Supported: {', '.join(sorted(POPULATION_KINDS))}")

    def _positive_int(key: str) -> int:
        raw = spec.get(key)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise ValueError(f"Population kind '{kind}' requires a positive integer '{key}'")
        return raw

    def _event_clause() -> str:
        raw = spec.get("event")
        if not raw or not isinstance(raw, str):
            raise ValueError(f"Population kind '{kind}' requires an 'event'")
        values["popk_event"] = raw
        return " AND event = {popk_event}"

    def _target_clause() -> str:
        if target_cond is None:
            raise ValueError(f"Population kind '{kind}' requires the pipeline's target predicate")
        return f" AND ({target_cond})"

    parts: list[str] = []
    values: dict[str, Any] = {}
    having: list[str] = []

    if kind == "performed_event_within_days":
        values["popk_days"] = _positive_int("days")
        event_clause = _event_clause() if spec.get("event") else ""
        if anchor_mode:
            if event_clause:
                parts.append(_members_within(now_expr, "lookback", predicate=event_clause))
            having.append(f"{_performed_before_t0(event_clause, days_param='popk_days')} = 1")
        else:
            parts.append(_members_within(now_expr, "popk_days", predicate=event_clause))
    elif kind == "person_first_seen_within_days":
        values["popk_days"] = _positive_int("days")
        if anchor_mode:
            having.append(f"min(toInt(toUnixTimestamp(e.person.created_at))) >= {_T0} - {{popk_days}} * 86400")
        else:
            parts.append(f"person.created_at >= {now_expr} - toIntervalDay({{popk_days}})")
    elif kind == "active_not_performed_target":
        values["popk_active_days"] = _positive_int("active_within_days")
        target_clause = _target_clause()
        if anchor_mode:
            having.append(f"{_performed_before_t0('', days_param='popk_active_days')} = 1")
            having.append(f"{_performed_before_t0(target_clause)} = 0")
        else:
            parts.append(_members_within(now_expr, "popk_active_days"))
            parts.append(_members_within(now_expr, "lookback", predicate=target_clause, negate=True))
    elif kind == "ever_performed_event":
        event_clause = _event_clause()
        # In anchor mode the row filter is a cheap superset (performed within the lookback
        # as of now); the HAVING narrows it to "performed before this user's T0".
        parts.append(_members_within(now_expr, "lookback", predicate=event_clause))
        if anchor_mode:
            having.append(f"{_performed_before_t0(event_clause)} = 1")
    elif kind == "ever_performed_target":
        target_clause = _target_clause()
        parts.append(_members_within(now_expr, "lookback", predicate=target_clause))
        if anchor_mode:
            having.append(f"{_performed_before_t0(target_clause)} = 1")

    return _CompiledPopulationKind(where_parts=parts, values=values, anchor_having_parts=having)


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
        # Scope the lookup to the pipeline's team so a foreign action id can't leak across tenants.
        action = Action.objects.get(id=action_id, team=team)
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
) -> tuple[str, dict[str, Any]]:
    """
    Build the WITH clause that materialises the labeled_users table:
        labeled_users(person_id, t0_ts, positive)
    Caller appends `SELECT ... FROM labeled_users` to use it.

    Population membership is decided per user at T0. Person-property filters and
    the kinds' cheap superset fragments narrow the events scan; event-property
    filters and the semantic kinds are evaluated in the labeled_users HAVING
    against each user's own anchor, so the training population is the same one
    inference selects as of its cutoff.

    sample_limit caps user_window for fast wizard previews; None = full
    materialization (trainer).
    """
    training_properties = (training_population or {}).get("properties", []) if training_population else []
    compiled_filters = _compile_population_filters(training_properties)
    target_cond, target_values = build_target_condition(
        target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_kind = _build_population_kind_conditions(training_population, anchor_mode=True, target_cond=target_cond)
    all_parts = compiled_filters.where_parts + compiled_kind.where_parts
    training_clause = f" AND ({' AND '.join(all_parts)})" if all_parts else ""
    identified_clause = _identified_users_and_clause()
    # A bare LIMIT would hand back whatever ClickHouse reads first, which correlates with
    # storage order; the sampled base rate is extrapolated to the whole population, so order
    # by a uniform hash of the person to make the sample representative and reproducible.
    limit_clause = (
        f"\n              ORDER BY cityHash64(toString(person_id))\n              LIMIT {int(sample_limit)}"
        if sample_limit is not None
        else ""
    )

    having_parts = [f"{_performed_before_t0(f' AND ({part})')} = 1" for part in compiled_filters.event_parts]
    having_parts.extend(compiled_kind.anchor_having_parts)
    anchor_having = f"\n              HAVING {' AND '.join(having_parts)}" if having_parts else ""

    # T0 sits at a fixed fraction (hash / 2^31) of the user's [first_ts, cutoff_ts) span. A
    # `hash % span` remainder would change every time cutoff_ts moved with now(), handing the
    # same person a different T0, features, and label on each run.
    cte = f"""
        WITH user_window AS (
            SELECT
                person_id,
                toInt(toUnixTimestamp(min(timestamp))) AS first_ts,
                toInt(toUnixTimestamp(now() - toIntervalDay({{horizon}}))) AS cutoff_ts
            FROM events
            WHERE timestamp >= now() - toIntervalDay({{lookback}})
              AND timestamp < now(){training_clause}{identified_clause}
            GROUP BY person_id
            HAVING first_ts < cutoff_ts{limit_clause}
        ),
        user_t0 AS (
            SELECT
                person_id,
                first_ts
                  + intDiv((cutoff_ts - first_ts) * toInt(bitAnd(cityHash64(toString(person_id)), 2147483647)), 2147483648)
                  AS t0_ts
            FROM user_window
        ),
        labeled_users AS (
            SELECT
                u.person_id AS person_id,
                u.t0_ts AS t0_ts,
                max(
                    {target_cond}
                    AND toInt(toUnixTimestamp(e.timestamp)) >= u.t0_ts
                    AND toInt(toUnixTimestamp(e.timestamp)) < u.t0_ts + ({{horizon}} * 86400)
                ) AS positive
            FROM events e
            INNER JOIN user_t0 u ON e.person_id = u.person_id
            WHERE e.timestamp >= now() - toIntervalDay({{lookback}})
              AND e.timestamp < now()
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
) -> tuple[str, dict[str, Any]]:
    """
    Build a HogQL query that returns one row of (eligible, positives) for a
    random-T0-per-user labeler. Used by the wizard for live base-rate feedback.

    eligible: users in the training_population with at least one event before
              now - horizon_days (so a horizon window fits in the data).
    positives: of those, users who fire target_event in [T0, T0 + horizon).

    With sample_limit=None this gives the trainer's actual eligible count;
    with sample_limit=N it gives an unbiased estimator computed over N users.
    """
    cte, values = _build_labeled_users_cte(
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
        sample_limit=sample_limit,
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
    random-T0 labeler — i.e. users in the training_population with at least one event
    before now - horizon_days. Used as the UI headline number so the wizard reports
    the full population size, not the sampled subset.

    Returns two columns: ``eligible`` (the v1 headline — restricted to identified
    users when IDENTIFIED_USERS_ONLY is on) and ``eligible_all`` (the same count
    without the identified restriction). The caller divides the two to detect a
    mostly-anonymous population and warn that v1 excludes the anonymous remainder.
    """
    training_properties = (training_population or {}).get("properties", []) if training_population else []
    train_parts, train_values = _build_population_conditions(training_properties)
    # Row mode: the target-relative kinds are evaluated as of now() here, which is an
    # approximation of the trainer's per-user-at-T0 semantics — acceptable for an
    # advisory headline count.
    target_cond, target_values = _target_condition_for(
        training_population, target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_kind = _build_population_kind_conditions(training_population, target_cond=target_cond)
    all_parts = train_parts + compiled_kind.where_parts
    training_clause = f" AND ({' AND '.join(all_parts)})" if all_parts else ""

    horizon_cond = "timestamp < now() - toIntervalDay({horizon})"
    eligible_cond = f"{horizon_cond} AND person.is_identified" if IDENTIFIED_USERS_ONLY else horizon_cond

    sql = f"""
        SELECT
            countDistinctIf(person_id, {eligible_cond}) AS eligible,
            countDistinctIf(person_id, {horizon_cond}) AS eligible_all
        FROM events
        WHERE timestamp >= now() - toIntervalDay({{lookback}})
          AND timestamp < now(){training_clause}
    """
    values: dict[str, Any] = {
        "horizon": horizon_days,
        "lookback": lookback_days,
        **target_values,
        **train_values,
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
) -> tuple[str, dict[str, Any]]:
    """
    Build a HogQL query producing (person_id, cutoff_ts) rows for scoring.

    cutoff_ts defaults to now() for every row — at inference time we score "the
    user's state as of right now." Pass an explicit ``cutoff_ts`` (unix seconds)
    to backfill a historical prediction date: features are then computed strictly
    before that instant, exactly as live scoring would have on that day. Eligible
    = users in inference_population with at least one event in the lookback_days
    window before the cutoff (so there's signal to score on).

    Substituted as the {anchors} table when running the agent's feature_sql
    at inference time. Same SQL the trainer executed against per-user T0;
    only the anchors table changes.
    """
    inference_properties = (inference_population or {}).get("properties", []) if inference_population else []
    inf_parts, inf_values = _build_population_conditions(inference_properties)

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
    all_parts = inf_parts + compiled_kind.where_parts
    inf_clause = f" AND ({' AND '.join(all_parts)})" if all_parts else ""
    identified_clause = _identified_users_and_clause()

    sql = f"""
        SELECT DISTINCT
            person_id,
            {cutoff_select} AS cutoff_ts
        FROM events
        WHERE timestamp >= {cutoff_expr} - toIntervalDay({{lookback}})
          AND timestamp < {cutoff_expr}{inf_clause}{identified_clause}
    """
    values: dict[str, Any] = {
        "lookback": lookback_days,
        **target_values,
        **inf_values,
        **compiled_kind.values,
    }
    if cutoff_ts is not None:
        values["cutoff_ts"] = cutoff_ts
    return sql, values


def strip_sql_comments(sql: str) -> str:
    """
    Remove ``--`` line comments and ``/* */`` block comments from HogQL, leaving
    string/identifier literals intact.

    Agent-authored feature SQL routinely carries comments. Blindly substituting
    ``{anchors}`` with a multi-line subquery that happens to land inside a ``--``
    comment injects newlines that escape the comment and corrupt the parse, and a
    comment can also swallow the rest of a line it was never meant to. Stripping
    comments before substitution sidesteps both. Single-quoted strings (with the
    ``''`` escape), double-quoted identifiers, and backtick identifiers are
    preserved verbatim so a literal ``--`` or ``/*`` inside them is not mistaken
    for a comment.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    quote: str | None = None  # one of ' " ` when inside a literal
    while i < n:
        ch = sql[i]
        if quote is not None:
            out.append(ch)
            if ch == quote:
                # '' inside a single-quoted string is an escaped quote, not a close.
                if quote == "'" and i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            continue  # leave the newline so adjacent tokens don't fuse
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2  # skip the closing */
            out.append(" ")  # block comment may sit mid-expression; keep a separator
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _substitute_anchors(feature_sql: str, anchors_subquery: str) -> str:
    """
    Substitute the agent's `{anchors}` placeholder with the actual per-user
    cutoff subquery. The contract from Step B's static validator guarantees
    the placeholder is present.

    Comments are stripped first so a placeholder sitting in (or adjacent to) a
    comment can't break the substituted SQL — see ``strip_sql_comments``.
    """
    return strip_sql_comments(feature_sql).replace("{anchors}", anchors_subquery)


def build_training_features_sql(
    *,
    feature_sql: str,
    target_event: str,
    horizon_days: int,
    lookback_days: int,
    training_population: dict[str, Any] | None,
    target_definition: dict[str, Any] | None = None,
    team: "Team | None" = None,
) -> tuple[str, dict[str, Any]]:
    """
    Build the composite training-time query:
      labeled_users CTE  +  labeled_anchors (adds fold)
      + agent's feature_sql (with {anchors} substituted to per-user T0)
      + JOIN back to labels/fold so each feature row has (__label, __fold)

    Caller substitutes {lookback_days} in feature_sql before calling. Returns
    one row per eligible user with the agent's feature columns plus __label
    and __fold for the train/holdout split.
    """
    cte, values = _build_labeled_users_cte(
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        horizon_days=horizon_days,
        lookback_days=lookback_days,
        training_population=training_population,
        sample_limit=None,
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
) -> tuple[str, dict[str, Any]]:
    """
    Build the inference-time query: the agent's feature_sql with {anchors}
    substituted with the inference anchors (cutoff_ts = now() per user, or a
    backdated instant when ``cutoff_ts`` is given for a historical backfill).
    Returns one row per eligible scoring user with the agent's feature
    columns — no labels, no fold.

    Caller substitutes {lookback_days} in feature_sql before calling.
    """
    anchors_sql, anchors_values = build_inference_anchors_sql(
        lookback_days=lookback_days,
        inference_population=inference_population,
        cutoff_ts=cutoff_ts,
        target_event=target_event,
        target_definition=target_definition,
        team=team,
    )
    # Wrap the inference anchors query as the {anchors} subquery — agent's
    # feature_sql references columns (person_id, cutoff_ts) just like training.
    anchors_subquery = f"({anchors_sql.strip()})"
    substituted_feature_sql = _substitute_anchors(feature_sql, anchors_subquery)
    return substituted_feature_sql, anchors_values
