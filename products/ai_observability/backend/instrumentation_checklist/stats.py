from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models.team import Team

from .grading import ChecklistStats

# Matches ai_events' `retention_days Int16 DEFAULT 30`, so the window never asks for rows the
# table has already dropped.
WINDOW_DAYS = 30

# The four structural event types. The AI meta-events ($ai_metric, $ai_feedback, $ai_evaluation)
# are annotations, not instrumentation, and would inflate the trace_structure denominator.
CHECKLIST_EVENTS = ("$ai_generation", "$ai_span", "$ai_trace", "$ai_embedding")

# Tool definitions come from the native `tools` column, never `properties.$ai_tools`: the ai_events
# materialized view strips heavy properties out of the JSON blob, so a properties read returns a
# silent zero and the checklist would warn that tool instrumentation is broken when it is fine.
#
# The identity counts exclude OTel-ingested generations because `is_identified` cannot read them.
# An unidentified OTel span falls back to one random UUID per OTLP request
# (rust/capture/src/otel/identity.rs), not to the trace id the server SDKs reuse, so a hex trace id
# never equals it and every such generation would look identified. Counting them would tell an
# all-OTel project its users are identified while its Users tab fills with per-request UUIDs.
#
# Column aliases are the ChecklistStats field names. `_row_to_stats` maps by name, so a renamed
# column raises instead of shifting a count onto the wrong check.
_STATS_SQL = """
SELECT
    countIf(is_generation)                                   AS generations,
    countIf(has_session)                                     AS events_with_session,
    countIf(declines_session)                                AS events_declining_session,
    countIf(is_generation AND has_tool_calls)                AS generations_with_tool_calls,
    countIf(is_generation AND has_tools_declared)            AS generations_with_tools_declared,
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
        -- `tools` holds the raw JSON, so an SDK that always sends `$ai_tools: []` stores '[]'. A
        -- non-empty test would read that as declared definitions and accuse a working SDK of not
        -- reporting the calls it makes.
        JSONLength(coalesce(tools, '')) > 0                     AS has_tools_declared,
        coalesce(properties.$ai_ingestion_source, '') = 'otel'  AS is_otel,
        distinct_id != coalesce(trace_id, '')                   AS is_identified,
        coalesce(parent_id, '') != ''                           AS has_parent
    FROM posthog.ai_events AS ai_events
    WHERE event IN {checklist_events}
      AND timestamp >= {date_from}
)
"""


def _row_to_stats(columns: Sequence[str], row: Sequence[int]) -> ChecklistStats:
    return ChecklistStats(**dict(zip(columns, row)))


def fetch_checklist_stats(team: Team) -> ChecklistStats:
    """Count the instrumentation signals the checklist grades, over the last WINDOW_DAYS days."""
    # `fall_back_to_events=False` keeps the stripped events table out of the result: it has no
    # `tools` column, so a fallback would read zero declared tools and warn falsely. The ungrouped
    # aggregate returns exactly one row even for a project with no AI events, so it never raises.
    result = query_ai_events(
        query=parse_select(_STATS_SQL),
        placeholders={
            "checklist_events": ast.Constant(value=list(CHECKLIST_EVENTS)),
            "date_from": ast.Constant(value=datetime.now(UTC) - timedelta(days=WINDOW_DAYS)),
        },
        team=team,
        query_type="AIObservabilityInstrumentationChecklist",
        fall_back_to_events=False,
    )
    return _row_to_stats(result.columns, result.results[0])
