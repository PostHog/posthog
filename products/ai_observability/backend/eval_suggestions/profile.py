"""Stage 2: what a team's AI traffic looks like, from aggregates and from one sample of its traces.

Aggregates read `events`, which a team's time range prunes to the rows it asks for. Contents come from
the sample that `measure.py` hydrates from `ai_events`, so this module never scans contents.
"""

import re
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from .queries import run_query
from .stats import wilson_interval

# One tool taking this share of all calls routes the agent's work, so calling it often is the design.
DISPATCHER_SHARE = 0.8
# A custom property is a segment when it splits traffic into a few named parts.
MAX_SEGMENT_VALUES = 20
# Absolute rather than a share of traffic: a property one AI feature sends, such as its review stage,
# segments that feature even when other features send most of the team's generations.
MIN_SEGMENT_GENERATIONS = 50
# Aggregates that parse `properties` read whole traces from a hash sample of about this many generations,
# then scale counts back. Shares need no scaling. The largest teams send tens of millions a week.
PROFILE_SAMPLE_GENERATIONS = 200_000
# The sample keeps whole traces. `$ai_trace_id` is materialized, so the filter runs before any JSON is parsed.
# Shared by Python and the segments query, ASCII digits only, so both count the same normalized values.
NUMERIC_SUFFIX_PATTERN = "[-_ .#]?[0-9]+$"
NUMERIC_SUFFIX = re.compile(NUMERIC_SUFFIX_PATTERN)

# Structured-output gaps: a field value one segment uses far more than its siblings.
MIN_GAP_ITEMS = 30
# Each side needs this many traces, so one long response cannot carry a gap alone.
MIN_GAP_TRACES = 5
MIN_GAP_RATIO = 3.0
# A value joins the tested set when the segment uses it this much more; the set as a whole must reach MIN_GAP_RATIO.
MIN_VALUE_RATIO = 1.5
MIN_GAP_DIFFERENCE = 0.15
MAX_ENUM_VALUES = 8
MAX_ENUM_VALUE_LENGTH = 32
FieldMeaning = Literal["urgency", "status", "label"]
# Only fields whose values a card can name in plain words are compared. An identifier such as a file name also
# has few values, and they cluster by segment for reasons nobody needs to check. A judgment such as `confidence`
# or `grade` has no meaning a card can state without explaining the app's own scale first.
FIELD_MEANINGS: dict[str, FieldMeaning] = {
    "priority": "urgency",
    "severity": "urgency",
    "urgency": "urgency",
    "status": "status",
    "outcome": "status",
    "label": "label",
    "category": "label",
}
CAMEL_CASE_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
ENUM_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,23}$")


@frozen
class ProfileWindow:
    start: datetime
    end: datetime


@frozen
class TeamProfile:
    generations: int
    traces: int
    # Distinct conversations, which a session judge runs once each.
    sessions: int
    # Keyed by whole days before the window end, so bucket 0 is the last 24 hours.
    generations_by_days_ago: dict[int, int]
    traces_by_days_ago: dict[int, int]
    tool_call_share: float
    tool_counts: dict[str, int]
    dispatcher_tools: tuple[str, ...]
    session_share: float
    error_share: float
    mean_input_tokens: float | None
    models: tuple[str, ...]
    error_prefixes: tuple[str, ...]
    # Custom property -> normalized value -> generations, for properties that read as segments.
    segments: dict[str, dict[str, int]]

    @classmethod
    def empty(cls) -> "TeamProfile":
        return cls(
            generations=0,
            traces=0,
            sessions=0,
            generations_by_days_ago={},
            traces_by_days_ago={},
            tool_call_share=0.0,
            tool_counts={},
            dispatcher_tools=(),
            session_share=0.0,
            error_share=0.0,
            mean_input_tokens=None,
            models=(),
            error_prefixes=(),
            segments={},
        )


# Reads only sort-key and materialized columns, so it costs little even on the largest teams.
_COUNT_SQL = """
SELECT count(), uniqIf(toString(properties.$ai_session_id), notEmpty(toString(properties.$ai_session_id)))
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
    countIf(toString(properties.$ai_is_error) = 'true') AS errors,
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
    SELECT arrayJoin(splitByChar(',', toString(properties.$ai_tools_called))) AS tool
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
  AND toString(properties.$ai_is_error) = 'true'
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
        WHERE NOT startsWith(key, '$') AND notEmpty(value) AND length(value) <= 64
        GROUP BY key, value
    )
    GROUP BY key
    HAVING length(pairs) <= {max_values}
)
ARRAY JOIN pairs AS pair
LIMIT 10000
"""


def normalize_segment_value(value: Any) -> str:
    return NUMERIC_SUFFIX.sub("", str(value)) if value is not None else ""


def dispatcher_tools(tool_counts: Mapping[str, int]) -> tuple[str, ...]:
    total = sum(tool_counts.values())
    return tuple(tool for tool, calls in tool_counts.items() if total and calls / total > DISPATCHER_SHARE)


def sample_per_mille(generations: int) -> int:
    if generations <= PROFILE_SAMPLE_GENERATIONS:
        return 1000
    return max(1, math.ceil(1000 * PROFILE_SAMPLE_GENERATIONS / generations))


def segments_from_rows(rows: Iterable[tuple[Any, ...]]) -> dict[str, dict[str, int]]:
    by_key: defaultdict[str, dict[str, int]] = defaultdict(dict)
    for key, value, count in rows:
        by_key[str(key)][str(value)] = int(count)
    return {
        key: values
        for key, values in by_key.items()
        if 2 <= len(values) <= MAX_SEGMENT_VALUES and sum(values.values()) >= MIN_SEGMENT_GENERATIONS
    }


def fetch_profile(team: Team, window: ProfileWindow) -> TeamProfile:
    placeholders: dict[str, ast.Expr] = {
        "start": ast.Constant(value=window.start),
        "end": ast.Constant(value=window.end),
    }
    count_rows = run_query(team, _COUNT_SQL, placeholders, "EvalSuggestionsProfileCount")
    generations = int(count_rows[0][0]) if count_rows else 0
    sessions = int(count_rows[0][1]) if count_rows else 0
    if generations == 0:
        return TeamProfile.empty()
    per_mille = sample_per_mille(generations)
    scale = 1000 / per_mille
    sampled = {
        **placeholders,
        "per_mille": ast.Constant(value=per_mille),
    }
    daily = run_query(team, _DAILY_SQL, sampled, "EvalSuggestionsProfileDaily")
    sampled_generations = sum(int(row[1]) for row in daily)
    with_tokens = sum(int(row[7]) for row in daily)
    models = Counter(model for row in daily for model in row[8] if model)
    tool_counts = {
        tool.strip(): round(int(calls) * scale)
        for tool, calls in run_query(team, _TOOLS_SQL, sampled, "EvalSuggestionsProfileTools")
        if tool and tool.strip()
    }
    # Errors are rare and filter on a materialized column, so they are counted on every row.
    error_rows = run_query(team, _ERRORS_SQL, placeholders, "EvalSuggestionsProfileErrors")
    segment_rows = [
        (key, value, round(count * scale))
        for key, value, count in run_query(
            team,
            _SEGMENTS_SQL,
            {
                **sampled,
                "max_values": ast.Constant(value=MAX_SEGMENT_VALUES),
                "numeric_suffix": ast.Constant(value=NUMERIC_SUFFIX_PATTERN),
            },
            "EvalSuggestionsProfileSegments",
        )
    ]

    def share(column: int) -> float:
        return sum(int(row[column]) for row in daily) / sampled_generations if sampled_generations else 0.0

    return TeamProfile(
        generations=generations,
        sessions=sessions,
        traces=round(sum(int(row[2]) for row in daily) * scale),
        generations_by_days_ago={int(row[0]): round(int(row[1]) * scale) for row in daily},
        traces_by_days_ago={int(row[0]): round(int(row[2]) * scale) for row in daily},
        tool_call_share=share(3),
        tool_counts=tool_counts,
        dispatcher_tools=dispatcher_tools(tool_counts),
        session_share=share(4),
        error_share=share(5),
        mean_input_tokens=sum(float(row[6] or 0) for row in daily) / with_tokens if with_tokens else None,
        models=tuple(model for model, _ in models.most_common(3)),
        error_prefixes=tuple(str(row[0]) for row in error_rows if row[0]),
        segments=segments_from_rows(segment_rows),
    )


@frozen
class StructuredOutput:
    """The final output of one sampled trace, reduced to the short string fields it holds."""

    trace_id: str
    segments: Mapping[str, str]
    fields: Mapping[str, Sequence[str]]


@frozen
class GapExample:
    trace_id: str
    # Items with a flagged value, out of all the trace's items in the field.
    matching: int
    total: int


@frozen
class StructuredGap:
    field: str
    meaning: FieldMeaning
    values: tuple[str, ...]
    segment_key: str
    segment_value: str
    segment_rate: float
    other_rate: float
    segment_items: int
    other_items: int
    # Most flagged first.
    examples: tuple[GapExample, ...]

    @property
    def items(self) -> str:
        """What the field describes, named after the list that holds it: `findings[].priority` is on "findings"."""
        lists = [part.removesuffix("[]") for part in self.field.split(".") if part.endswith("[]")]
        return lists[-1].replace("_", " ") if lists else "responses"

    @property
    def field_name(self) -> str:
        return self.field.rsplit(".", 1)[-1]


def field_meaning(field: str) -> FieldMeaning | None:
    """What a field's values mean, from the words of its own name: `findings[].riskPriority` holds an urgency."""
    words = re.findall(r"[a-z]+", CAMEL_CASE_BOUNDARY.sub(r"\1 \2", field.rsplit(".", 1)[-1]).lower())
    return next((FIELD_MEANINGS[word] for word in words if word in FIELD_MEANINGS), None)


def parse_structured(text: str) -> Any:
    """The JSON an output carries, also when a model wrapped it in a code fence. None when it is prose."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def short_string_fields(value: Any, path: str = "", depth: int = 0) -> dict[str, list[str]]:
    """Every short string at every path of a JSON value: `findings[].priority -> ["P1", "P3"]`."""
    found: defaultdict[str, list[str]] = defaultdict(list)
    if depth > 4:
        return found
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(child, str):
                if 0 < len(child) <= MAX_ENUM_VALUE_LENGTH and len(child.split()) <= 3:
                    found[child_path].append(child)
            else:
                for nested_path, values in short_string_fields(child, child_path, depth + 1).items():
                    found[nested_path].extend(values)
    elif isinstance(value, list):
        for child in value[:200]:
            for nested_path, values in short_string_fields(child, f"{path}[]", depth + 1).items():
                found[nested_path].extend(values)
    return found


def _enum_fields(outputs: Sequence[StructuredOutput]) -> dict[str, FieldMeaning]:
    totals: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for output in outputs:
        for field, values in output.fields.items():
            totals[field].update(values)
    return {
        field: meaning
        for field, counts in totals.items()
        if (meaning := field_meaning(field)) is not None
        and sum(counts.values()) >= MIN_GAP_ITEMS
        and 2 <= len(counts) <= MAX_ENUM_VALUES
        and all(ENUM_VALUE.match(value) for value in counts)
    }


@frozen
class SegmentRates:
    inside: int
    inside_total: int
    outside: int
    outside_total: int
    # Traces that hold any item on each side. Items of one response are not independent observations.
    inside_traces: int = 0
    outside_traces: int = 0


def _rates(
    outputs: Sequence[StructuredOutput], field: str, segment_key: str, segment_value: str, values: Sequence[str]
) -> SegmentRates:
    """Matching and total items inside the segment, and in its sibling segments."""
    inside = inside_total = outside = outside_total = inside_traces = outside_traces = 0
    for output in outputs:
        segment = output.segments.get(segment_key)
        if segment is None:
            continue
        items = output.fields.get(field, ())
        matching = sum(1 for item in items if item in values)
        if segment == segment_value:
            inside, inside_total = inside + matching, inside_total + len(items)
            inside_traces += bool(items)
        else:
            outside, outside_total = outside + matching, outside_total + len(items)
            outside_traces += bool(items)
    return SegmentRates(
        inside=inside,
        inside_total=inside_total,
        outside=outside,
        outside_total=outside_total,
        inside_traces=inside_traces,
        outside_traces=outside_traces,
    )


def _over_represented(
    outputs: Sequence[StructuredOutput], field: str, segment_key: str, segment_value: str, values: Sequence[str]
) -> list[str]:
    """Values the segment uses at least MIN_VALUE_RATIO times as often as its siblings."""
    over = []
    for value in values:
        rates = _rates(outputs, field, segment_key, segment_value, [value])
        if (
            rates.inside
            and rates.inside_total
            and rates.outside_total
            and rates.inside / rates.inside_total >= MIN_VALUE_RATIO * rates.outside / rates.outside_total
        ):
            over.append(value)
    return over


def find_structured_gaps(outputs: Sequence[StructuredOutput]) -> list[StructuredGap]:
    """Field values one segment uses far more than its sibling segments do.

    The values a segment over-uses are tested together, because a severity scale splits one judgment over
    several values: P0 and P1 can each look close to their siblings while "must-fix" as a whole does not.
    The set counts when the segment uses it MIN_GAP_RATIO times as often, at least MIN_GAP_DIFFERENCE more,
    and the two Wilson intervals do not overlap.
    """
    gaps: list[StructuredGap] = []
    segment_keys = sorted({key for output in outputs for key in output.segments})
    for field, meaning in _enum_fields(outputs).items():
        values = sorted({value for output in outputs for value in output.fields.get(field, ())})
        for segment_key in segment_keys:
            segment_values = sorted({o.segments[segment_key] for o in outputs if segment_key in o.segments})
            if len(segment_values) < 2:
                continue
            for segment_value in segment_values:
                flagged = _over_represented(outputs, field, segment_key, segment_value, values)
                if not flagged:
                    continue
                rates = _rates(outputs, field, segment_key, segment_value, flagged)
                if rates.inside_total < MIN_GAP_ITEMS or rates.outside_total < MIN_GAP_ITEMS:
                    continue
                if rates.inside_traces < MIN_GAP_TRACES or rates.outside_traces < MIN_GAP_TRACES:
                    continue
                inside_rate, outside_rate = rates.inside / rates.inside_total, rates.outside / rates.outside_total
                if (
                    inside_rate < MIN_GAP_RATIO * outside_rate
                    or inside_rate - outside_rate < MIN_GAP_DIFFERENCE
                    or wilson_interval(rates.inside, rates.inside_total).low
                    <= wilson_interval(rates.outside, rates.outside_total).high
                ):
                    continue
                gaps.append(
                    StructuredGap(
                        field=field,
                        meaning=meaning,
                        values=tuple(flagged),
                        segment_key=segment_key,
                        segment_value=segment_value,
                        segment_rate=inside_rate,
                        other_rate=outside_rate,
                        segment_items=rates.inside_total,
                        other_items=rates.outside_total,
                        examples=_examples(outputs, field, segment_key, segment_value, flagged),
                    )
                )
    return gaps


def _examples(
    outputs: Sequence[StructuredOutput], field: str, segment_key: str, segment_value: str, values: Sequence[str]
) -> tuple[GapExample, ...]:
    counted = []
    for output in outputs:
        if output.segments.get(segment_key) != segment_value:
            continue
        items = output.fields.get(field, ())
        matching = sum(1 for item in items if item in values)
        if matching:
            counted.append(GapExample(trace_id=output.trace_id, matching=matching, total=len(items)))
    return tuple(sorted(counted, key=lambda example: (-example.matching, example.trace_id)))


def gap_holds(gap: StructuredGap, outputs: Sequence[StructuredOutput]) -> bool | None:
    """Whether a gap found on the main sample shows again on held-out traces. None when they hold too few items."""
    rates = _rates(outputs, gap.field, gap.segment_key, gap.segment_value, gap.values)
    if rates.inside_total < MIN_GAP_ITEMS // 3 or rates.outside_total < MIN_GAP_ITEMS // 3:
        return None
    return rates.inside / rates.inside_total > rates.outside / rates.outside_total
