from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models.team import Team
from posthog.utils import generate_cache_key, get_safe_cache, safe_cache_set

from .grading import VOLUME_FLOOR, ChecklistStats

# Matches ai_events' `retention_days Int16 DEFAULT 30`, so the window never asks for rows the
# table has already dropped.
WINDOW_DAYS = 30

# Instrumentation only changes when someone edits and deploys their code, so a verdict stays true
# far longer than this. The person who just fixed something is the one case that cannot wait, and
# the card's Refresh button bypasses the cache for them.
CACHE_TTL_SECONDS = 15 * 60

# Bump when a change to the counts or the window makes an entry written by an older deploy wrong.
CACHE_VERSION = "v1"

# The four structural event types. The AI meta-events ($ai_metric, $ai_feedback, $ai_evaluation)
# are annotations, not instrumentation, and would inflate the trace_structure denominator.
CHECKLIST_EVENTS = ("$ai_generation", "$ai_span", "$ai_trace", "$ai_embedding")

# The identity counts exclude OTel-ingested generations because `is_identified` cannot read them.
# An unidentified OTel span falls back to one random UUID per OTLP request
# (rust/capture/src/otel/identity.rs), not to the trace id the server SDKs reuse, so a hex trace id
# never equals it and every such generation would look identified. Counting them would tell an
# all-OTel project its users are identified while its Users tab fills with per-request UUIDs.
#
# Column aliases are the ChecklistStats field names. `_row_to_counts` maps by name, so a renamed
# column raises instead of shifting a count onto the wrong check.
_COUNTS_SQL = """
SELECT
    countIf(is_generation)                                   AS generations,
    countIf(has_session)                                     AS events_with_session,
    countIf(declines_session)                                AS events_declining_session,
    countIf(is_generation AND has_tool_calls)                AS generations_with_tool_calls,
    countIf(is_generation AND NOT is_otel)                   AS sdk_generations,
    countIf(is_generation AND NOT is_otel AND is_identified) AS sdk_generations_identified,
    countIf(is_span)                                         AS spans,
    countIf(has_parent)                                      AS events_with_parent,
    count()                                                  AS total_events
FROM (
    SELECT
        event = '$ai_generation'                                AS is_generation,
        event = '$ai_span'                                      AS is_span,
        -- Any of the four event types can carry $ai_session_id, and the Sessions tab reads it off
        -- whichever one has it (see queries/sessions.sql), so flooring on generations alone would
        -- warn about a missing session id at a project whose Sessions tab works.
        coalesce(session_id, '') != ''                          AS has_session,
        -- An explicit null is a project saying this workload finishes in one trace, which is an
        -- answer rather than a gap. JSONType reads absent and null alike, so JSONHas is what
        -- separates them, and requiring type Null keeps an empty string (usually an unset
        -- variable) out of the opt-out.
        JSONHas(properties, '$ai_session_id')
            AND JSONType(properties, '$ai_session_id') = 'Null' AS declines_session,
        coalesce(properties.$ai_tools_called, '') != ''         AS has_tool_calls,
        coalesce(properties.$ai_ingestion_source, '') = 'otel'  AS is_otel,
        distinct_id != coalesce(trace_id, '')                   AS is_identified,
        coalesce(parent_id, '') != ''                           AS has_parent
    FROM posthog.ai_events AS ai_events
    WHERE event IN {checklist_events}
      AND timestamp >= {date_from}
)
"""

# `tools` is the widest column the checklist reads, and costs about as much as every other column
# it touches put together. Only one warning sentence reads it, so it gets its own query rather than
# a term in the aggregate every project pays for. `LIMIT 1` ends the scan at the first row that
# declares tools; a project that declares none is still read in full, so the caller skips this
# entirely unless the answer can change what someone sees.
#
# Tool definitions come from the native `tools` column, never `properties.$ai_tools`: the ai_events
# materialized view strips heavy properties out of the JSON blob, so a properties read returns a
# silent zero and the checklist would warn that tool instrumentation is broken when it is fine.
#
# `tools` holds the raw JSON, so an SDK that always sends `$ai_tools: []` stores '[]'. A non-empty
# test would read that as declared definitions and accuse a working SDK of not reporting the calls
# it makes.
_TOOLS_DECLARED_SQL = """
SELECT count() AS declared
FROM (
    SELECT 1 AS present
    FROM posthog.ai_events AS ai_events
    WHERE event = '$ai_generation'
      AND timestamp >= {date_from}
      AND JSONLength(coalesce(tools, '')) > 0
    LIMIT 1
)
"""


def _window_placeholders() -> dict[str, ast.Expr]:
    return {
        "checklist_events": ast.Constant(value=list(CHECKLIST_EVENTS)),
        "date_from": ast.Constant(value=datetime.now(UTC) - timedelta(days=WINDOW_DAYS)),
    }


def _row_to_counts(columns: Sequence[str], row: Sequence[int]) -> dict[str, int]:
    return dict(zip(columns, row))


def _query_counts(team: Team) -> dict[str, int]:
    # `fall_back_to_events=False` keeps the stripped events table out of the result: it carries the
    # AI properties under different names, so a fallback would read zeros and warn falsely. The
    # ungrouped aggregate returns exactly one row even for a project with no AI events, so it never
    # raises.
    result = query_ai_events(
        query=parse_select(_COUNTS_SQL),
        placeholders=_window_placeholders(),
        team=team,
        query_type="AIObservabilityInstrumentationChecklist",
        fall_back_to_events=False,
    )
    return _row_to_counts(result.columns, result.results[0])


def _query_tools_declared(team: Team) -> bool:
    result = query_ai_events(
        query=parse_select(_TOOLS_DECLARED_SQL),
        placeholders=_window_placeholders(),
        team=team,
        query_type="AIObservabilityInstrumentationChecklistToolsDeclared",
        fall_back_to_events=False,
    )
    return result.results[0][0] > 0


def _cache_key(team_id: int) -> str:
    return generate_cache_key(team_id, f"ai_observability_instrumentation_checklist_{CACHE_VERSION}_{WINDOW_DAYS}d")


def _stats_from_cache(cached: object) -> ChecklistStats | None:
    """Rebuild a cached entry by field name, or discard it.

    A frozen slots dataclass pickles its fields positionally, so an entry written before a field was
    added or removed would unpickle with every later value shifted onto the wrong field, and
    `__post_init__` does not run to catch it. Reconstructing from a plain dict makes that a cache
    miss instead. CACHE_VERSION still exists to avoid throwing away a whole team's entry on deploy.
    """
    if not isinstance(cached, dict):
        return None
    try:
        return ChecklistStats(**cached)
    except (TypeError, ValueError):
        return None


def _compute_checklist_stats(team: Team) -> ChecklistStats:
    counts = _query_counts(team)
    # Only the tool-calls warning reads this, and only once that check clears its volume floor with
    # no call recorded. Anywhere else the answer is discarded, so the wide read is skipped. `None`
    # says the question was never asked, which keeps a skipped read from reading as "declares none".
    asks_about_definitions = counts["generations"] >= VOLUME_FLOOR and counts["generations_with_tool_calls"] == 0
    return ChecklistStats(**counts, tools_declared=_query_tools_declared(team) if asks_about_definitions else None)


def fetch_checklist_stats(team: Team, *, force_refresh: bool = False) -> ChecklistStats:
    """Count the instrumentation signals the checklist grades, over the last WINDOW_DAYS days."""
    cache_key = _cache_key(team.pk)
    if not force_refresh:
        cached = _stats_from_cache(get_safe_cache(cache_key))
        if cached is not None:
            return cached

    stats = _compute_checklist_stats(team)
    # Below the floor every check grades pending, which is the card someone watches while their first
    # events land. Holding that verdict for the whole TTL is the wrong answer to look at, and a
    # project with that few events is cheap to count again.
    if stats.total_events >= VOLUME_FLOOR:
        safe_cache_set(cache_key, asdict(stats), timeout=CACHE_TTL_SECONDS)
    return stats
