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
  high bit is set, which would make `% positive` return negative offsets and
  place T0 before first_ts. Truncating to the lower 31 bits via bitAnd
  guarantees a non-negative dividend without harming uniformity (we only need
  ~24 bits anyway: max window 365d * 86400s ≈ 3.2e7).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

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
# api/serializers.py imports this set, so an uncompilable kind is rejected at creation.
POPULATION_KINDS = frozenset(
    {
        "performed_event_within_days",
        "person_first_seen_within_days",
        "active_not_performed_target",
        "ever_performed_event",
    }
)

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


def _build_population_conditions(
    properties: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """
    Translate a list of PostHog property filter dicts into HogQL WHERE condition
    strings and a values dict for parameterized binding.

    Property types:
    - "person"  → person.properties[<key>]  (events table context)
    - "event"   → properties[<key>]

    Operators: exact, is_not, icontains, not_icontains, gt, gte, lt, lte,
               is_set, is_not_set.

    The property key is bound as a HogQL value (a parameterized subscript,
    ``properties[{param}]``) rather than interpolated into the query text, so any
    key — including PostHog system properties like ``$browser`` — is safe without
    an allowlist. Unsupported types/operators are skipped with a warning rather
    than raising. Lives in labeling.py (not inference.py) because labeling.py is
    the lower-level SQL-building layer that inference.py and validation.py both
    depend on.
    """
    parts: list[str] = []
    values: dict[str, Any] = {}

    for i, prop in enumerate(properties):
        key = prop.get("key")
        prop_type = prop.get("type", "person")
        operator = prop.get("operator", "exact")
        value = prop.get("value")

        if not key:
            logger.warning("autoresearch_population_missing_key", key=key)
            continue

        if prop_type == "person":
            map_expr = "person.properties"
        elif prop_type == "event":
            map_expr = "properties"
        else:
            logger.warning("autoresearch_population_unsupported_prop_type", prop_type=prop_type)
            continue

        # Bind the key as a value (parameterized subscript) — never interpolate it into SQL text.
        key_param = f"pop_k_{i}"
        values[key_param] = str(key)
        field = f"{map_expr}[{{{key_param}}}]"

        param = f"pop_{i}"

        if operator == "is_set":
            parts.append(f"isNotNull({field}) AND {field} != ''")
        elif operator == "is_not_set":
            parts.append(f"(isNull({field}) OR {field} = '')")
        elif operator == "exact":
            if isinstance(value, list):
                in_params = [f"pop_{i}_{j}" for j in range(len(value))]
                for j, v in enumerate(value):
                    values[f"pop_{i}_{j}"] = v
                in_refs = ", ".join("{" + p + "}" for p in in_params)
                parts.append(f"{field} IN ({in_refs})")
            else:
                values[param] = value
                parts.append(f"{field} = {{{param}}}")
        elif operator == "is_not":
            if isinstance(value, list):
                in_params = [f"pop_{i}_{j}" for j in range(len(value))]
                for j, v in enumerate(value):
                    values[f"pop_{i}_{j}"] = v
                in_refs = ", ".join("{" + p + "}" for p in in_params)
                parts.append(f"{field} NOT IN ({in_refs})")
            else:
                values[param] = value
                parts.append(f"{field} != {{{param}}}")
        elif operator == "icontains":
            values[param] = f"%{value}%"
            parts.append(f"{field} ILIKE {{{param}}}")
        elif operator == "not_icontains":
            values[param] = f"%{value}%"
            parts.append(f"{field} NOT ILIKE {{{param}}}")
        elif operator in ("gt", "gte", "lt", "lte"):
            op_sql = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[operator]
            values[param] = value
            parts.append(f"toFloat64OrNull({field}) {op_sql} {{{param}}}")
        else:
            logger.warning("autoresearch_population_unsupported_operator", operator=operator)

    return parts, values


@dataclass(frozen=True, kw_only=True)
class _CompiledPopulationKind:
    where_parts: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    # Training-only refinement applied per user at T0 in the labeled_users CTE:
    # "performed_before" keeps only users who performed the target before their T0,
    # "not_performed_before" keeps only users who had not. None = fully expressed in where_parts.
    anchor_target_relation: Literal["performed_before", "not_performed_before"] | None = None


def _build_population_kind_conditions(
    population: dict[str, Any] | None,
    *,
    now_expr: str = "now()",
    anchor_mode: bool = False,
) -> _CompiledPopulationKind:
    """
    Compile a semantic population spec (``{"kind": ..., ...}``, produced by
    templates.py) into row-level HogQL WHERE fragments for an events scan.

    Membership subqueries are bounded to the caller's lookback window, so
    "ever performed" and "has not performed" mean "within the lookback window" —
    the scan cost stays proportional to the data the query already reads. The
    emitted fragments reference the ``{lookback}`` bound value, which every
    population-consuming builder in this module binds.

    ``now_expr`` is the anchor instant — ``now()`` for live queries, or a bound
    backfill cutoff expression for historical scoring. All time windows are
    computed relative to it.

    ``anchor_mode=True`` (training) moves the target-performed test from a
    row-level filter to a per-user-at-T0 refinement via ``anchor_target_relation``,
    which ``_build_labeled_users_cte`` applies against each user's T0. This matters
    for correctness, not just fidelity: excluding "ever performed the target" users
    with a row filter at training time would remove exactly the users whose post-T0
    adoption provides the positive labels.

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

    def _event() -> str:
        raw = spec.get("event")
        if not raw or not isinstance(raw, str):
            raise ValueError(f"Population kind '{kind}' requires an 'event'")
        return raw

    parts: list[str] = []
    values: dict[str, Any] = {}
    anchor_target_relation: Literal["performed_before", "not_performed_before"] | None = None

    if kind == "performed_event_within_days":
        values["popk_days"] = _positive_int("days")
        event_clause = ""
        if spec.get("event"):
            values["popk_event"] = _event()
            event_clause = " AND event = {popk_event}"
        parts.append(
            "person_id IN (SELECT DISTINCT person_id FROM events"
            f" WHERE timestamp >= {now_expr} - toIntervalDay({{popk_days}})"
            f" AND timestamp < {now_expr}{event_clause})"
        )
    elif kind == "person_first_seen_within_days":
        values["popk_days"] = _positive_int("days")
        parts.append(f"person.created_at >= {now_expr} - toIntervalDay({{popk_days}})")
    elif kind == "active_not_performed_target":
        values["popk_active_days"] = _positive_int("active_within_days")
        parts.append(
            "person_id IN (SELECT DISTINCT person_id FROM events"
            f" WHERE timestamp >= {now_expr} - toIntervalDay({{popk_active_days}})"
            f" AND timestamp < {now_expr})"
        )
        if anchor_mode:
            anchor_target_relation = "not_performed_before"
        else:
            values["popk_event"] = _event()
            parts.append(
                "person_id NOT IN (SELECT DISTINCT person_id FROM events"
                f" WHERE event = {{popk_event}} AND timestamp >= {now_expr} - toIntervalDay({{lookback}})"
                f" AND timestamp < {now_expr})"
            )
    elif kind == "ever_performed_event":
        values["popk_event"] = _event()
        parts.append(
            "person_id IN (SELECT DISTINCT person_id FROM events"
            f" WHERE event = {{popk_event}} AND timestamp >= {now_expr} - toIntervalDay({{lookback}})"
            f" AND timestamp < {now_expr})"
        )
        if anchor_mode:
            # The row filter is a cheap superset (performed within lookback as of now);
            # the anchor refinement narrows it to "performed before this user's T0".
            anchor_target_relation = "performed_before"

    return _CompiledPopulationKind(where_parts=parts, values=values, anchor_target_relation=anchor_target_relation)


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

    sample_limit caps user_window for fast wizard previews; None = full
    materialization (trainer).
    """
    training_properties = (training_population or {}).get("properties", []) if training_population else []
    train_parts, train_values = _build_population_conditions(training_properties)
    compiled_kind = _build_population_kind_conditions(training_population, anchor_mode=True)
    all_parts = train_parts + compiled_kind.where_parts
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
    target_cond, target_values = build_target_condition(
        target_event=target_event, target_definition=target_definition, team=team
    )

    # Per-user-at-T0 population refinement for target-relative kinds (see
    # _build_population_kind_conditions): membership is decided against each
    # user's own T0, exactly as inference decides it against its cutoff.
    anchor_having = ""
    if compiled_kind.anchor_target_relation is not None:
        wanted = 1 if compiled_kind.anchor_target_relation == "performed_before" else 0
        anchor_having = (
            f"\n              HAVING max(({target_cond}) AND toInt(toUnixTimestamp(e.timestamp)) < u.t0_ts) = {wanted}"
        )

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
                  + (toInt(bitAnd(cityHash64(toString(person_id)), 2147483647)) % (cutoff_ts - first_ts))
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
        **train_values,
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
    compiled_kind = _build_population_kind_conditions(training_population)
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
        **train_values,
        **compiled_kind.values,
    }
    return sql, values


def build_inference_anchors_sql(
    *,
    lookback_days: int,
    inference_population: dict[str, Any] | None,
    cutoff_ts: int | None = None,
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
    compiled_kind = _build_population_kind_conditions(inference_population, now_expr=cutoff_expr)
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
    )
    # Wrap the inference anchors query as the {anchors} subquery — agent's
    # feature_sql references columns (person_id, cutoff_ts) just like training.
    anchors_subquery = f"({anchors_sql.strip()})"
    substituted_feature_sql = _substitute_anchors(feature_sql, anchors_subquery)
    return substituted_feature_sql, anchors_values
