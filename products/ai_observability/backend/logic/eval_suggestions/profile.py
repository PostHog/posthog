"""Stage 2: what a team's AI traffic looks like, from aggregates and from one sample of its traces.

Aggregates read `events`, which a team's time range prunes to the rows it asks for. Contents come from
the sample that `measure.py` hydrates from `ai_events`, so this module never scans contents.
"""

import re
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions.profile_queries import (
    MAX_SEGMENT_VALUE_LENGTH,
    MAX_SEGMENT_VALUES,
    NUMERIC_SUFFIX_PATTERN,
    DailyTrafficRow,
    ErrorPrefixRow,
    ProfileWindow,
    SegmentValueRow,
    ToolCallsRow,
    TrafficCounts,
    load_daily_traffic,
    load_error_prefixes,
    load_segment_values,
    load_tool_calls,
    load_traffic_counts,
)

from .stats import wilson_interval

# One tool taking this share of all calls routes the agent's work, so calling it often is the design.
DISPATCHER_SHARE = 0.8
# Gap search tests every segment key against every enum field in Python, so a team that sends thousands of
# custom properties or output fields must not set its cost. The keys and fields with the most data stay.
MAX_SEGMENT_KEYS = 10
MAX_ENUM_FIELDS = 10
# Absolute rather than a share of traffic: a property one AI feature sends, such as its review stage,
# segments that feature even when other features send most of the team's generations.
MIN_SEGMENT_GENERATIONS = 50
# Aggregates that parse `properties` read whole traces from a hash sample of about this many generations,
# then scale counts back. Shares need no scaling. The largest teams send tens of millions a week.
# The sample keeps whole traces. `$ai_trace_id` is materialized, so the filter runs before any JSON is parsed.
PROFILE_SAMPLE_GENERATIONS = 200_000
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
SAFE_FIELD_PATH = re.compile(r"^[A-Za-z0-9_]{1,40}(\[\])?(\.[A-Za-z0-9_]{1,40}(\[\])?){0,3}$")
ENUM_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,23}$")


@frozen
class TeamProfile:
    generations: int
    traces: int
    # Distinct conversations, which a session judge runs once each, and the traces that belong to one.
    sessions: int
    session_traces: int
    # Keyed by whole days before the window end, so bucket 0 is the last 24 hours.
    generations_by_days_ago: dict[int, int]
    traces_by_days_ago: dict[int, int]
    tool_call_share: float
    tool_counts: dict[str, int]
    dispatcher_tools: tuple[str, ...]
    session_share: float
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
            session_traces=0,
            generations_by_days_ago={},
            traces_by_days_ago={},
            tool_call_share=0.0,
            tool_counts={},
            dispatcher_tools=(),
            session_share=0.0,
            mean_input_tokens=None,
            models=(),
            error_prefixes=(),
            segments={},
        )


def segment_text(value: Any) -> str:
    """A property value as ClickHouse prints it, so a boolean reads `true` as it does in profiling and filters."""
    return json.dumps(value) if isinstance(value, bool) else str(value)


def normalize_segment_value(value: Any) -> str:
    return NUMERIC_SUFFIX.sub("", segment_text(value)) if value is not None else ""


def dispatcher_tools(tool_counts: Mapping[str, int]) -> tuple[str, ...]:
    total = sum(tool_counts.values())
    return tuple(tool for tool, calls in tool_counts.items() if total and calls / total > DISPATCHER_SHARE)


def sample_per_mille(generations: int) -> int:
    if generations <= PROFILE_SAMPLE_GENERATIONS:
        return 1000
    return max(1, math.ceil(1000 * PROFILE_SAMPLE_GENERATIONS / generations))


def segments_from_rows(rows: Iterable[SegmentValueRow]) -> dict[str, dict[str, int]]:
    by_key: defaultdict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        by_key[row.key][row.value] = row.generations
    segments = {
        key: values
        for key, values in by_key.items()
        if 2 <= len(values) <= MAX_SEGMENT_VALUES and sum(values.values()) >= MIN_SEGMENT_GENERATIONS
    }
    kept = sorted(segments, key=lambda key: (-sum(segments[key].values()), key))[:MAX_SEGMENT_KEYS]
    return {key: segments[key] for key in kept}


def build_profile(
    counts: TrafficCounts,
    daily: Sequence[DailyTrafficRow],
    tools: Sequence[ToolCallsRow],
    errors: Sequence[ErrorPrefixRow],
    segments: Sequence[SegmentValueRow],
    per_mille: int,
) -> TeamProfile:
    """The profile from the counts over all traffic and the rows read from a `per_mille` sample of it."""
    if counts.generations == 0:
        return TeamProfile.empty()
    scale = 1000 / per_mille
    sampled_generations = sum(row.generations for row in daily)
    with_tokens = sum(row.with_input_tokens for row in daily)
    models = Counter(model for row in daily for model in row.models if model)
    tool_counts = {row.tool: round(row.calls * scale) for row in tools if row.tool}

    def share(column: Callable[[DailyTrafficRow], int]) -> float:
        return sum(column(row) for row in daily) / sampled_generations if sampled_generations else 0.0

    return TeamProfile(
        generations=counts.generations,
        sessions=counts.sessions,
        session_traces=counts.session_traces,
        traces=round(sum(row.traces for row in daily) * scale),
        generations_by_days_ago={row.days_ago: round(row.generations * scale) for row in daily},
        traces_by_days_ago={row.days_ago: round(row.traces * scale) for row in daily},
        tool_call_share=share(lambda row: row.with_tools),
        tool_counts=tool_counts,
        dispatcher_tools=dispatcher_tools(tool_counts),
        session_share=share(lambda row: row.with_session),
        mean_input_tokens=sum(row.input_tokens for row in daily) / with_tokens if with_tokens else None,
        models=tuple(model for model, _ in models.most_common(3)),
        error_prefixes=tuple(row.prefix for row in errors if row.prefix),
        segments=segments_from_rows(replace(row, generations=round(row.generations * scale)) for row in segments),
    )


def fetch_profile(team: Team, window: ProfileWindow) -> TeamProfile:
    counts = load_traffic_counts(team, window)
    if counts.generations == 0:
        return TeamProfile.empty()
    per_mille = sample_per_mille(counts.generations)
    return build_profile(
        counts,
        load_daily_traffic(team, window, per_mille),
        load_tool_calls(team, window, per_mille),
        # Errors are rare and filter on a materialized column, so they are counted on every row.
        load_error_prefixes(team, window),
        load_segment_values(team, window, per_mille),
        per_mille,
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
        stripped = stripped.strip("`")
        stripped = (stripped[4:] if stripped[:4].lower() == "json" else stripped).strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        return json.loads(stripped)
    except (ValueError, RecursionError):
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
    fields = {
        field: meaning
        for field, counts in totals.items()
        # The field path goes into a judge prompt, so only plain identifiers qualify, never free text from an output.
        if SAFE_FIELD_PATH.fullmatch(field)
        and (meaning := field_meaning(field)) is not None
        and sum(counts.values()) >= MIN_GAP_ITEMS
        and 2 <= len(counts) <= MAX_ENUM_VALUES
        and all(ENUM_VALUE.fullmatch(value) for value in counts)
    }
    kept = sorted(fields, key=lambda field: (-sum(totals[field].values()), field))[:MAX_ENUM_FIELDS]
    return {field: fields[field] for field in kept}


@frozen
class SegmentRates:
    inside: int
    inside_total: int
    outside: int
    outside_total: int
    # Items of one response are not independent observations, so confidence is judged over traces: how many traces
    # have a flagged item inside the segment, and any item outside it, and the sum of each trace's flagged share.
    inside_traces: int = 0
    outside_traces: int = 0
    inside_trace_items: int = 0
    inside_share: float = 0.0
    outside_share: float = 0.0


def _rates(
    outputs: Sequence[StructuredOutput], field: str, segment_key: str, segment_value: str, values: Sequence[str]
) -> SegmentRates:
    """Matching and total items inside the segment, and in its sibling segments."""
    inside = inside_total = outside = outside_total = inside_traces = outside_traces = inside_trace_items = 0
    inside_share = outside_share = 0.0
    for output in outputs:
        segment = output.segments.get(segment_key)
        items = output.fields.get(field, ())
        if segment is None or not items:
            continue
        matching = sum(1 for item in items if item in values)
        if segment == segment_value:
            inside, inside_total = inside + matching, inside_total + len(items)
            inside_traces += matching > 0
            inside_trace_items += 1
            inside_share += matching / len(items)
        else:
            outside, outside_total = outside + matching, outside_total + len(items)
            outside_traces += 1
            outside_share += matching / len(items)
    return SegmentRates(
        inside=inside,
        inside_total=inside_total,
        outside=outside,
        outside_total=outside_total,
        inside_traces=inside_traces,
        outside_traces=outside_traces,
        inside_trace_items=inside_trace_items,
        inside_share=inside_share,
        outside_share=outside_share,
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
    and the Wilson intervals of the per-trace shares do not overlap.
    """
    gaps: list[StructuredGap] = []
    segment_keys = sorted({key for output in outputs for key in output.segments})
    for field, meaning in _enum_fields(outputs).items():
        values = sorted({value for output in outputs for value in output.fields.get(field, ())})
        for segment_key in segment_keys:
            # The same bound as the profile's segment query, so gap search never names a value profiling would drop.
            segment_values = sorted(
                {
                    value
                    for o in outputs
                    if len(value := o.segments.get(segment_key, "")) <= MAX_SEGMENT_VALUE_LENGTH and value
                }
            )
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
                    or wilson_interval(rates.inside_share, rates.inside_trace_items).low
                    <= wilson_interval(rates.outside_share, rates.outside_traces).high
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
