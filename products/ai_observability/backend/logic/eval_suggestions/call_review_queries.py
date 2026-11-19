"""Reads for the review stage: a team's busiest call types, then a spread of calls from the ones triage picked."""

from collections.abc import Mapping, Sequence

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

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
# Calls a review's code check is counted on, per call type, so its rate rests on more than the calls the review read.
CODE_CHECK_CALLS_PER_CALL_TYPE = 200
MAX_INPUT_CHARS = 65536
MAX_OUTPUT_CHARS = 16384
# Agent tool catalogs often run to around 100 KB, and the runtime judge formats the whole catalog.
MAX_TOOLS_CHARS = 262_144
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

# Per call type and snippet, in the order of {names} and {patterns}: the sampled generations whose input holds the
# snippet, and how many of them are of the call type. ILIKE matches the case-insensitive contains an evaluation
# condition runs. ai_events can hold copies of a generation, so each counts once, as in the call type counts. The
# arrays count every pair in one pass, so no input is copied once per pair.
_SNIPPET_MATCHES_SQL = f"""
SELECT
    sumForEach(arrayMap(pattern -> toInt(input ILIKE pattern), {{patterns}})) AS matched,
    sumForEach(
        arrayMap(
            (name, pattern) -> toInt(source = 'input' AND call_type = name AND input ILIKE pattern),
            {{names}},
            {{patterns}}
        )
    ) AS in_call_type
FROM (
    SELECT uuid, {_CALL_TYPE_COLUMNS}, input
    {_GENERATIONS}
    LIMIT 1 BY uuid
)
"""

# Candidates are chosen by a hash of their uuid, which spreads each call type's candidates over the day. The
# subquery chooses them from ids and call types alone, so the sort never holds message bodies, and only the chosen
# rows read their input and output. ai_events can store an event more than once, so both caps count each uuid once.
# The subquery's `IN` runs as GLOBAL IN, see _calls_query.
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
    ) AS output_text,
    left(coalesce(tools, ''), {{max_tools}}) AS tools_text
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


class _GlobalSubqueryIn(TraversingVisitor):
    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op == ast.CompareOperationOp.In and isinstance(node.right, ast.SelectQuery):
            node.op = ast.CompareOperationOp.GlobalIn
        super().visit_compare_operation(node)


def _calls_query() -> ast.SelectQuery:
    """_CALLS_SQL with its candidate subquery run once, on the node that starts the query. A plain `IN` over the
    distributed ai_events table runs the subquery again on every shard, and HogQL has no GLOBAL IN syntax."""
    query = parse_select(_CALLS_SQL)
    assert isinstance(query, ast.SelectQuery)
    _GlobalSubqueryIn().visit(query)
    return query


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
class SnippetMatches:
    # Sampled generations whose input holds the snippet.
    matched: int
    # Of those, the ones in the snippet's call type.
    in_call_type: int


@frozen
class ReviewCallRow:
    event_uuid: str
    trace_id: str
    call_type: str
    # Raw JSON, cut to the caps above, which can leave it unparseable.
    input: str
    output: str
    # The `$ai_tools` catalog, which the runtime judge reads beside the call.
    tools: str = ""


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


def snippet_matches(
    team: Team, window: ProfileWindow, per_mille: int, snippets: Mapping[str, Sequence[str]]
) -> dict[str, list[SnippetMatches]]:
    """Counts the matches of each input-named call type's snippets, keyed by call type name, in one scan of a
    `per_mille` hash sample."""
    pairs = [(name, f"%{snippet}%") for name, candidates in snippets.items() for snippet in candidates]
    rows = run_ai_events_query(
        team,
        _SNIPPET_MATCHES_SQL,
        {
            **_placeholders(window, per_mille),
            "names": ast.Constant(value=[name for name, _ in pairs]),
            "patterns": ast.Constant(value=[pattern for _, pattern in pairs]),
        },
        "EvalSuggestionsSnippetMatches",
    )
    matched, in_call_type = rows[0] if rows and rows[0][0] else ([0] * len(pairs), [0] * len(pairs))
    counts = iter(
        SnippetMatches(matched=int(found), in_call_type=int(own)) for found, own in zip(matched, in_call_type)
    )
    return {name: [next(counts) for _ in candidates] for name, candidates in snippets.items()}


def load_review_calls(
    team: Team,
    window: ProfileWindow,
    per_mille: int,
    call_types: Sequence[CallTypeRow],
    per_type: int = CANDIDATES_PER_CALL_TYPE,
) -> list[ReviewCallRow]:
    rows = run_ai_events_query(
        team,
        _calls_query(),
        {
            **_placeholders(window, per_mille),
            "keys": ast.Constant(value=[call_type.key for call_type in call_types]),
            "max_input": ast.Constant(value=MAX_INPUT_CHARS),
            "max_first": ast.Constant(value=MAX_FIRST_MESSAGE_CHARS),
            "max_last": ast.Constant(value=MAX_LAST_MESSAGE_CHARS),
            "last_messages": ast.Constant(value=LAST_MESSAGES),
            "max_output": ast.Constant(value=MAX_OUTPUT_CHARS),
            "max_tools": ast.Constant(value=MAX_TOOLS_CHARS),
            "per_type": ast.Constant(value=per_type),
            # Without a limit, HogQL returns its default 100 rows, fewer than the candidates of two call types.
            "max_rows": ast.Constant(value=per_type * len(call_types)),
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
            tools=str(row[6] or ""),
        )
        for row in rows
    ]
