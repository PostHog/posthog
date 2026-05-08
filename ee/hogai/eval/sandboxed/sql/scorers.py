"""SQL scorers for the sandboxed coding-agent evals.

Extracts the final ``execute-sql`` MCP tool call the agent made and grades
the HogQL query against an expected reference query. Mirrors the trends /
funnel / retention judges in shape but lives outside ``product_analytics/``
because ``execute-sql`` is a general-purpose tool, not a product-analytics
one.

The judge prompt is forked from the CI ``SQL_SEMANTICS_CORRECTNESS_PROMPT``
in ``ee/hogai/eval/scorers/sql.py`` — same HogQL guidance, but graded on
the six-bucket ``GRADED_ALIGNMENT_*`` scale used by the rest of the
sandboxed evals instead of binary Pass/Fail. The ``database_schema``
placeholder is dropped: the sandboxed run doesn't surface a schema dump
to scorers, and the judge has the user prompt + reference SQL to anchor
on without it.

The shared judge plumbing (``JudgedScorer``, ``parser_for``,
``user_prompt``, alignment constants, ``JUDGE_MODEL``) is cross-imported
from ``product_analytics/scorers.py``.
That's a layering smell — they're general-purpose helpers tied to a
domain folder by accident — but with only this one new consumer, the
fix-up belongs in a follow-up refactor when a third general-purpose eval
(warehouse, system tables, persons CRUD) lands. Don't lift speculatively.
"""

from __future__ import annotations

from typing import Any

from braintrust import Score

from ee.hogai.eval.sandboxed.product_analytics.scorers import (
    GRADED_ALIGNMENT_CHOICE_SCORES,
    GRADED_ALIGNMENT_RUBRIC,
    JUDGE_MODEL,
    JudgedScorer,
    parser_for,
    user_prompt,
)

QUERY_SQL_TOOL_NAME = "execute-sql"
_MAX_RESULT_CHARS_FOR_JUDGE = 12_000


def extract_last_execute_sql_call(output: dict[str, Any] | None) -> dict[str, str] | None:
    """Return the query and result from the most recent successful ``execute-sql`` call.

    Returns ``None`` when the agent never ran the tool successfully — scorers
    should short-circuit in that case rather than count it as an incorrect
    answer.
    """
    parser = parser_for(output)
    if parser is None:
        return None

    successful = [call for call in parser.get_tool_calls(QUERY_SQL_TOOL_NAME) if not call.is_error]
    if not successful:
        return None

    call = successful[-1]
    query = call.input.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return {"query": query, "result": call.output}


def extract_last_execute_sql_query(output: dict[str, Any] | None) -> str | None:
    """Return the query string from the most recent successful ``execute-sql`` call."""
    call = extract_last_execute_sql_call(output)
    if call is not None:
        return call["query"]
    return None


def _truncate_result_for_judge(result: str) -> str:
    if len(result) <= _MAX_RESULT_CHARS_FOR_JUDGE:
        return result
    return f"{result[:_MAX_RESULT_CHARS_FOR_JUDGE]}\n\n...[truncated for judge]..."


SQL_SCHEMA_ALIGNMENT_PROMPT = """
You are an expert ClickHouse SQL auditor judging whether an agent-produced HogQL query would equally answer the user's question, compared to a reference "ideal" query.

HogQL is an SQL flavor derived from ClickHouse SQL, with PostHog-specific syntax:
- JSON property access via `.`, like `SELECT properties.$browser FROM events`
- Nested table access, like `SELECT person.properties.foo FROM events`
- `sessions` table with session-level fields (`session.$session_duration` etc.)

The bar is **semantic equivalence**, not strict field equality. Multiple correct queries can answer the same prompt — accept the actual query if a reasonable analyst would consider it an equally valid way to answer the user's question. Reject only when a logical difference could yield different output under some valid database state.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Material aspects to compare:
1. **Result shape**: rows and columns the query returns. Column aliases, ordering, and trivial formatting differences are fine. Different result shape (e.g. one row vs many, missing aggregates the prompt asked for) is a miss.
2. **Filters**: WHERE / HAVING clauses must produce the same row set. Time predicates must be equivalent (e.g. `now() - INTERVAL 7 DAY` vs `timestamp >= today() - 7`). Event-name and property filters are case-sensitive.
3. **Aggregations**: same grouping keys, same aggregate functions, same handling of NULLs and duplicates. `count(distinct person_id)` and `count(distinct distinct_id)` are NOT equivalent for unique-user counts.
4. **Joins and subqueries**: same join keys, same join type (INNER vs LEFT), same conversion of correlated subqueries to joins. CTEs vs subqueries are equivalent when the join shape matches.
5. **Sequence / ordering logic**: when the prompt asks about an ordered sequence ("in this order", "before", "after"), the actual query must enforce ordering (window functions, timestamp comparisons). When the prompt asks for "regardless of order", a count-distinct of events is fine.
6. **Time-bucketing**: `toStartOfWeek(timestamp, 1)` (Monday-start) and `toStartOfWeek(timestamp)` (Sunday-start) are NOT equivalent when the prompt specifies a week start. `date_trunc('week', ...)` defaults vary by engine.
7. **Limits and ordering**: when the prompt asks for "top N" or "5 users", `LIMIT` and `ORDER BY` must be present and consistent. Missing them is a miss.

Penalize:
- Wrong identifier for unique users: must be `person_id` or `person.id`, NOT `distinct_id`.
- Wrong field for session duration: must be `session.$session_duration`, NOT `properties.$session_duration`.
- Missing time window when the prompt specifies one.
- Aggregating without the requested grouping (e.g. "by browser" but no `GROUP BY browser`).
- Subtle NULL-handling mistakes that change the count (e.g. `count(*)` vs `count(col)` when `col` can be NULL and the prompt asks "how many rows").

Ignore:
- Column aliases, output column ordering, whitespace, capitalization of keywords.
- Choice of CTE vs subquery vs derived table when the join shape is the same.
- LIMIT 100 added defensively when the prompt didn't ask for a limit.

<expected_query>
{{expected.sql_query}}
</expected_query>

<actual_query>
{{output.sql_query}}
</actual_query>
""".strip()


class SQLSchemaAlignment(JudgedScorer):
    """Graded score: how well does the actual HogQL query match the expected one?

    Semantic comparison rather than strict text equality — multiple correct
    queries can answer the same prompt. Same six-bucket gradation as the
    typed-query alignment scorers in ``product_analytics/scorers.py``.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        actual = extract_last_execute_sql_query(output)
        if actual is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran execute-sql successfully"},
            )
        expected_query = (expected or {}).get("sql_query") if isinstance(expected, dict) else None
        if not isinstance(expected_query, str) or not expected_query.strip():
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No expected.sql_query provided"},
            )
        return {
            "output": {"sql_query": actual, "prompt": user_prompt(output)},
            "expected": {"sql_query": expected_query},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="sql_schema_alignment",
            prompt_template=SQL_SCHEMA_ALIGNMENT_PROMPT + "\n\n" + GRADED_ALIGNMENT_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


SQL_RESULT_MESSAGE_ALIGNMENT_RUBRIC = """
How would you rate the assistant's final answer? Choose one:
- perfect: Directly answers the user, faithfully summarizes the executed SQL result, and includes the important values or conclusion.
- near_perfect: Answers the user and is faithful to the result, with only small omissions or extra detail.
- slightly_off: Mostly answers the user, but misses a minor result detail or includes slightly confusing framing.
- somewhat_misaligned: Partly related, but omits important result information, over-focuses on SQL rather than the answer, or is hard for the user to act on.
- strongly_misaligned: Substantially contradicts the executed result, answers a different question, or only provides a query with no useful result interpretation.
- useless: No meaningful final answer, fabricated answer, or impossible to evaluate.

Be strict about factual faithfulness. Do not reward a fluent answer that invents values not present in the SQL result.
""".strip()


SQL_RESULT_MESSAGE_ALIGNMENT_PROMPT = """
You are an expert analytics QA reviewer judging whether an agent's final response correctly answers the user's question after running HogQL.

The agent was required to execute SQL and then answer the user from the SQL result.
Judge only the final assistant message, using the user prompt, executed query, and SQL result as evidence.

Accept:
- A concise natural-language answer.
- A short table or bullet list when the user asked for grouped or ranked results.
- Including the executed SQL, as long as the message also answers the user.

Penalize:
- Only returning SQL or implementation details without interpreting the result.
- Omitting the key values or conclusion from the SQL result.
- Copying a large raw result table without a useful answer.
- Contradicting the SQL result or inventing values that are not supported by it.
- Saying the data is unavailable when the executed result contains relevant rows.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Executed HogQL:
<executed_query>
{{output.sql_query}}
</executed_query>

SQL result:
<sql_result>
{{output.sql_result}}
</sql_result>

Final assistant message:
<final_message>
{{output.final_message}}
</final_message>
""".strip()


class SQLResultMessageAlignment(JudgedScorer):
    """Graded score: did the final message answer the user from the SQL result?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:  # noqa: ARG002
        executed = extract_last_execute_sql_call(output)
        if executed is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran execute-sql successfully"},
            )

        parser = parser_for(output)
        final_message = parser.get_final_agent_message() if parser is not None else None
        if not isinstance(final_message, str) or not final_message.strip():
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No final assistant message found"},
            )

        return {
            "output": {
                "prompt": user_prompt(output),
                "sql_query": executed["query"],
                "sql_result": _truncate_result_for_judge(executed["result"]),
                "final_message": final_message,
            },
            "expected": {},
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="sql_result_message_alignment",
            prompt_template=SQL_RESULT_MESSAGE_ALIGNMENT_PROMPT + "\n\n" + SQL_RESULT_MESSAGE_ALIGNMENT_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )
