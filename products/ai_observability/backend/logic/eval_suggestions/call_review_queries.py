"""Reads for the review stage: a team's busiest call types, then a spread of calls from the ones triage picked."""

from collections.abc import Sequence

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from .profile_queries import ProfileWindow
from .queries import run_ai_events_query

TRIAGE_CALL_TYPES = 25
EXAMPLE_INPUT_CHARS = 1500
# Calls without a managed prompt or span name are grouped by the start of their input, which holds the system prompt.
CALL_TYPE_INPUT_CHARS = 1200
# Candidates read per picked call type. Selection skips tool-call-only outputs and caps calls per trace, so it
# needs several times its share to choose from.
CANDIDATES_PER_CALL_TYPE = 60
MAX_INPUT_CHARS = 65536
MAX_OUTPUT_CHARS = 16384
# A longer input keeps its first message, which holds the system prompt, and its last few messages, each within a cap.
MAX_FIRST_MESSAGE_CHARS = 49152
MAX_LAST_MESSAGE_CHARS = 16384
LAST_MESSAGES = 6

_CALL_TYPE_COLUMNS = """
        multiIf(
            notEmpty(coalesce(prompt_name, '')), 'prompt_name',
            notEmpty(coalesce(span_name, '')), 'span_name',
            'input'
        ) AS source,
        multiIf(
            source = 'prompt_name', prompt_name,
            source = 'span_name', span_name,
            toString(cityHash64(left(input, {key_chars})))
        ) AS call_type"""

# A generation without a trace id is left out: selection caps calls per trace, so all of them would count as one
# trace, and a card's examples link to traces.
_GENERATIONS = """
    FROM posthog.ai_events AS ai_events
    WHERE event = '$ai_generation'
      AND timestamp >= {start}
      AND timestamp < {end}
      AND notEmpty(coalesce(model, ''))
      AND notEmpty(coalesce(input, ''))
      AND notEmpty(trace_id)
      AND cityHash64(trace_id) % 1000 < {per_mille}"""

_CALL_TYPES_SQL = f"""
SELECT source, call_type, count(DISTINCT uuid) AS calls, any(model) AS model, any(example_input) AS example_input
FROM (
    SELECT uuid, {_CALL_TYPE_COLUMNS}, model, left(input, {{example_chars}}) AS example_input
    {_GENERATIONS}
)
GROUP BY source, call_type
ORDER BY calls DESC, call_type
LIMIT {{limit}}
"""

# Candidates are chosen by a hash of their uuid, which spreads each call type's candidates over the day. The
# subquery chooses them from ids and call types alone, so the sort never holds message bodies, and only the chosen
# rows read their input and output. ai_events can store an event more than once, so both caps count each uuid once.
_CALLS_SQL = f"""
SELECT
    toString(uuid) AS event_uuid,
    trace_id,
    {_CALL_TYPE_COLUMNS},
    if(
        length(input) <= {{max_input}},
        input,
        if(
            startsWith(input, '['),
            concat(
                '[',
                arrayStringConcat(
                    arrayConcat(
                        arrayFilter(m -> length(m) <= {{max_first}}, arraySlice(JSONExtractArrayRaw(input), 1, 1)),
                        arrayFilter(
                            m -> length(m) <= {{max_last}},
                            arraySlice(
                                JSONExtractArrayRaw(input),
                                greatest(2, length(JSONExtractArrayRaw(input)) - {{last_messages}} + 1)
                            )
                        )
                    ),
                    ','
                ),
                ']'
            ),
            left(input, {{max_input}})
        )
    ) AS input_text,
    left(
        if(coalesce(output_choices, '') NOT IN ('', 'null', '[]'), output_choices, coalesce(output, '')),
        {{max_output}}
    ) AS output_text
{_GENERATIONS}
  AND uuid IN (
    SELECT uuid
    FROM (
        SELECT uuid, {_CALL_TYPE_COLUMNS}
        {_GENERATIONS}
        LIMIT 1 BY uuid
    )
    WHERE concat(source, ':', call_type) IN {{keys}}
    ORDER BY cityHash64(toString(uuid))
    LIMIT {{per_type}} BY source, call_type
  )
ORDER BY cityHash64(event_uuid)
LIMIT 1 BY event_uuid
LIMIT {{max_rows}}
"""


@frozen
class CallTypeRow:
    # Which property names the call type: prompt_name, span_name, or input when neither is set.
    source: str
    # The prompt or span name, or a hash of the start of the input.
    name: str
    # Estimated calls in the day read, scaled up from the hash sample.
    calls: int
    model: str
    example_input: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.name}"


@frozen
class ReviewCallRow:
    event_uuid: str
    trace_id: str
    call_type: str
    # Raw JSON, cut to the caps above, which can leave it unparseable.
    input: str
    output: str


def _placeholders(window: ProfileWindow, per_mille: int) -> dict[str, ast.Expr]:
    return {
        "start": ast.Constant(value=window.start),
        "end": ast.Constant(value=window.end),
        "per_mille": ast.Constant(value=per_mille),
        "key_chars": ast.Constant(value=CALL_TYPE_INPUT_CHARS),
    }


def load_call_types(team: Team, window: ProfileWindow, per_mille: int) -> list[CallTypeRow]:
    """The busiest call types among generations with a model and an input, from a `per_mille` hash sample of traces."""
    rows = run_ai_events_query(
        team,
        _CALL_TYPES_SQL,
        {
            **_placeholders(window, per_mille),
            "example_chars": ast.Constant(value=EXAMPLE_INPUT_CHARS),
            "limit": ast.Constant(value=TRIAGE_CALL_TYPES),
        },
        "EvalSuggestionsReviewCallTypes",
    )
    scale = 1000 / per_mille
    return [
        CallTypeRow(
            source=str(row[0]),
            name=str(row[1]),
            calls=round(int(row[2]) * scale),
            model=str(row[3] or ""),
            example_input=str(row[4] or ""),
        )
        for row in rows
    ]


def load_review_calls(
    team: Team, window: ProfileWindow, per_mille: int, call_types: Sequence[CallTypeRow]
) -> list[ReviewCallRow]:
    rows = run_ai_events_query(
        team,
        _CALLS_SQL,
        {
            **_placeholders(window, per_mille),
            "keys": ast.Constant(value=[call_type.key for call_type in call_types]),
            "max_input": ast.Constant(value=MAX_INPUT_CHARS),
            "max_first": ast.Constant(value=MAX_FIRST_MESSAGE_CHARS),
            "max_last": ast.Constant(value=MAX_LAST_MESSAGE_CHARS),
            "last_messages": ast.Constant(value=LAST_MESSAGES),
            "max_output": ast.Constant(value=MAX_OUTPUT_CHARS),
            "per_type": ast.Constant(value=CANDIDATES_PER_CALL_TYPE),
            # Without a limit, HogQL returns its default 100 rows, fewer than the candidates of two call types.
            "max_rows": ast.Constant(value=CANDIDATES_PER_CALL_TYPE * len(call_types)),
        },
        "EvalSuggestionsReviewCalls",
    )
    return [
        ReviewCallRow(
            event_uuid=str(row[0]),
            trace_id=str(row[1]),
            call_type=f"{row[2]}:{row[3]}",
            input=str(row[4] or ""),
            output=str(row[5] or ""),
        )
        for row in rows
    ]
