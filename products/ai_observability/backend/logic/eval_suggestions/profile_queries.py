from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from .queries import run_query

# A custom property is a segment when it splits traffic into a few named parts.
MAX_SEGMENT_VALUES = 20
# Longer values read as ids or free text, not names, and a card or eval name built from one would overflow.
MAX_SEGMENT_VALUE_LENGTH = 64
# Shared by Python and the segments query, ASCII digits only, so both count the same normalized values.
# The separator is required, so versions such as `v1` and `v2` stay apart.
NUMERIC_SUFFIX_PATTERN = "[-_ .#][0-9]+$"


@frozen
class ProfileWindow:
    start: datetime
    end: datetime


# Reads only sort-key and materialized columns, so it costs little even on the largest teams.
_COUNT_SQL = """
SELECT
    count(),
    uniqIf(toString(properties.$ai_session_id), notEmpty(toString(properties.$ai_session_id))),
    uniqIf(toString(properties.$ai_trace_id), notEmpty(toString(properties.$ai_session_id)))
FROM events
WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end}
"""

_DAILY_SQL = """
SELECT
    intDiv(dateDiff('second', timestamp, {end}), 86400) AS days_ago,
    count() AS generations,
    uniq(properties.$ai_trace_id) AS traces,
    countIf(toFloat(properties.$ai_tool_call_count) > 0 OR notEmpty(toString(properties.$ai_tools_called))) AS with_tools,
    countIf(notEmpty(toString(properties.$ai_session_id))) AS with_session,
    sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
    countIf(isNotNull(toFloat(properties.$ai_input_tokens))) AS with_input_tokens,
    topK(3)(toString(properties.$ai_model)) AS models
FROM events
WHERE event = '$ai_generation'
  AND timestamp >= {start}
  AND timestamp < {end}
  AND cityHash64(toString(properties.$ai_trace_id)) % 1000 < {per_mille}
GROUP BY days_ago
"""

_TOOLS_SQL = """
SELECT tool, count() AS calls
FROM (
    SELECT arrayJoin(arrayMap(name -> trim(name), splitByChar(',', toString(properties.$ai_tools_called)))) AS tool
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= {start}
      AND timestamp < {end}
      AND cityHash64(toString(properties.$ai_trace_id)) % 1000 < {per_mille}
      AND notEmpty(toString(properties.$ai_tools_called))
)
GROUP BY tool
ORDER BY calls DESC
LIMIT 50
"""

_ERRORS_SQL = """
SELECT left(toString(properties.$ai_error), 60) AS prefix, count() AS errors
FROM events
WHERE event IN ('$ai_generation', '$ai_span')
  AND timestamp >= {start}
  AND timestamp < {end}
  AND (toString(properties.$ai_is_error) = 'true' OR notEmpty(toString(properties.$ai_error)))
GROUP BY prefix
ORDER BY errors DESC
LIMIT 20
"""

# Numeric suffixes are stripped before counting, so `lens-1` and `lens-2` count as one segment.
# Reads a hash sample of generations, so an ID-like property on a busy team can't grow the GROUP BY with traffic.
# Keys with too many values are dropped in the query, so no LIMIT can cut one down to a false segment.
_SEGMENTS_SQL = """
SELECT key, tupleElement(pair, 1) AS value, tupleElement(pair, 2) AS generations
FROM (
    SELECT key, groupArray((value, generations)) AS pairs
    FROM (
        SELECT key, value, count() AS generations
        FROM (
            SELECT
                arrayJoin(JSONExtractKeysAndValues(properties, 'String')) AS kv,
                tupleElement(kv, 1) AS key,
                replaceRegexpAll(tupleElement(kv, 2), {numeric_suffix}, '') AS value
            FROM events
            WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end}
              AND cityHash64(toString(properties.$ai_trace_id)) % 1000 < {per_mille}
        )
        WHERE NOT startsWith(key, '$') AND notEmpty(value) AND length(value) <= {max_value_length}
        GROUP BY key, value
    )
    GROUP BY key
    HAVING length(pairs) <= {max_values}
)
ARRAY JOIN pairs AS pair
LIMIT 10000
"""


@frozen
class TrafficCounts:
    generations: int
    sessions: int
    session_traces: int


@frozen
class DailyTrafficRow:
    """One day of the sampled generations, before scaling back to all traffic."""

    days_ago: int
    generations: int
    traces: int
    with_tools: int
    with_session: int
    input_tokens: float
    with_input_tokens: int
    models: tuple[str, ...]


@frozen
class ToolCallsRow:
    tool: str
    calls: int


@frozen
class ErrorPrefixRow:
    prefix: str
    errors: int


@frozen
class SegmentValueRow:
    key: str
    value: str
    generations: int


def _placeholders(window: ProfileWindow) -> dict[str, ast.Expr]:
    return {"start": ast.Constant(value=window.start), "end": ast.Constant(value=window.end)}


def _sampled(window: ProfileWindow, per_mille: int) -> dict[str, ast.Expr]:
    return {**_placeholders(window), "per_mille": ast.Constant(value=per_mille)}


def load_traffic_counts(team: Team, window: ProfileWindow) -> TrafficCounts:
    rows = run_query(team, _COUNT_SQL, _placeholders(window), "EvalSuggestionsProfileCount")
    if not rows:
        return TrafficCounts(generations=0, sessions=0, session_traces=0)
    return TrafficCounts(generations=int(rows[0][0]), sessions=int(rows[0][1]), session_traces=int(rows[0][2]))


def load_daily_traffic(team: Team, window: ProfileWindow, per_mille: int) -> list[DailyTrafficRow]:
    rows = run_query(team, _DAILY_SQL, _sampled(window, per_mille), "EvalSuggestionsProfileDaily")
    return [
        DailyTrafficRow(
            days_ago=int(row[0]),
            generations=int(row[1]),
            traces=int(row[2]),
            with_tools=int(row[3]),
            with_session=int(row[4]),
            input_tokens=float(row[5] or 0),
            with_input_tokens=int(row[6]),
            models=tuple(row[7]),
        )
        for row in rows
    ]


def load_tool_calls(team: Team, window: ProfileWindow, per_mille: int) -> list[ToolCallsRow]:
    rows = run_query(team, _TOOLS_SQL, _sampled(window, per_mille), "EvalSuggestionsProfileTools")
    return [ToolCallsRow(tool=str(row[0] or ""), calls=int(row[1])) for row in rows]


def load_error_prefixes(team: Team, window: ProfileWindow) -> list[ErrorPrefixRow]:
    rows = run_query(team, _ERRORS_SQL, _placeholders(window), "EvalSuggestionsProfileErrors")
    return [ErrorPrefixRow(prefix=str(row[0] or ""), errors=int(row[1])) for row in rows]


def load_segment_values(team: Team, window: ProfileWindow, per_mille: int) -> list[SegmentValueRow]:
    rows = run_query(
        team,
        _SEGMENTS_SQL,
        {
            **_sampled(window, per_mille),
            "max_values": ast.Constant(value=MAX_SEGMENT_VALUES),
            "numeric_suffix": ast.Constant(value=NUMERIC_SUFFIX_PATTERN),
            "max_value_length": ast.Constant(value=MAX_SEGMENT_VALUE_LENGTH),
        },
        "EvalSuggestionsProfileSegments",
    )
    return [SegmentValueRow(key=str(row[0]), value=str(row[1]), generations=int(row[2])) for row in rows]
