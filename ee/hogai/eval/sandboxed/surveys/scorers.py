"""Survey-analysis scorers for sandboxed agent evals."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.product_analytics.scorers import (
    GRADED_ALIGNMENT_CHOICE_SCORES,
    GRADED_ALIGNMENT_RUBRIC,
    INSIGHT_WRITE_TOOLS,
    JUDGE_MODEL,
    JudgedScorer,
    parser_for,
    user_prompt,
)
from ee.hogai.eval.sandboxed.sql.scorers import extract_last_execute_sql_call

SURVEY_RESPONSE_TOOL_NAME = "execute-sql"
SURVEY_WRITE_TOOLS = frozenset({"survey-create", "survey-update", "survey-delete"})
SURVEY_FORBIDDEN_WRITE_TOOLS = SURVEY_WRITE_TOOLS | INSIGHT_WRITE_TOOLS

_MAX_RESULT_CHARS_FOR_JUDGE = 14_000


def _truncate_for_judge(value: str) -> str:
    if len(value) <= _MAX_RESULT_CHARS_FOR_JUDGE:
        return value
    return f"{value[:_MAX_RESULT_CHARS_FOR_JUDGE]}\n\n...[truncated for judge]..."


def _survey_seed(output: dict[str, Any] | None) -> dict[str, Any] | None:
    if not output:
        return None
    seed = output.get("seed")
    if not isinstance(seed, dict):
        return None
    payload = seed.get("survey_analysis")
    return payload if isinstance(payload, dict) else None


def _expected_analysis(expected: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(expected, dict):
        return None
    payload = expected.get("survey_analysis")
    return payload if isinstance(payload, dict) else None


def _final_message(output: dict[str, Any] | None) -> str | None:
    parser = parser_for(output)
    if parser is not None:
        message = parser.get_final_agent_message()
        if isinstance(message, str) and message.strip():
            return message
    if output:
        fallback = output.get("last_message")
        if isinstance(fallback, str) and fallback.strip():
            return fallback
    return None


def _contains_string(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_contains_string(key, needle) or _contains_string(item, needle) for key, item in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_string(item, needle) for item in value)
    return False


class RequiredToolCallOrError(Scorer):
    """Binary scorer: did the agent attempt at least one required tool?

    Unlike ``RequiredToolCall``, errored calls count. This distinguishes
    routing failures from tool/runtime failures: the outcome judges still
    require successful response retrieval, but this scorer confirms the agent
    tried the required MCP path.
    """

    required: frozenset[str]
    _label: str

    def __init__(self, required: Iterable[str], *, name: str = "required_tool_call_or_error"):
        self.required = frozenset(required)
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        attempted = [call for call in parser.get_tool_calls() if call.name in self.required]
        if not attempted:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No required tool call found", "required": sorted(self.required)},
            )

        successful = sorted({call.name for call in attempted if not call.is_error})
        errored = sorted({call.name for call in attempted if call.is_error})
        return Score(
            name=self._name(),
            score=1.0,
            metadata={
                "required_tools_successful": successful,
                "required_tools_errored": errored,
            },
        )


class NoToolCallOrError(Scorer):
    """Binary scorer: did the agent avoid even attempting any forbidden tool?"""

    forbidden: frozenset[str]
    _label: str

    def __init__(self, forbidden: Iterable[str], *, name: str = "no_forbidden_tool_call_or_error"):
        self.forbidden = frozenset(forbidden)
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        attempted = [call for call in parser.get_tool_calls() if call.name in self.forbidden]
        if not attempted:
            return Score(name=self._name(), score=1.0, metadata={})

        successful = sorted({call.name for call in attempted if not call.is_error})
        errored = sorted({call.name for call in attempted if call.is_error})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "forbidden_tools_successful": successful,
                "forbidden_tools_errored": errored,
            },
        )


class SurveyIdUsed(Scorer):
    """Binary scorer: did the agent use the seeded survey ID in its own tool inputs?

    Tool outputs don't count, since the MCP server may return the ID during
    discovery. The model needs to carry that ID into a later call, typically
    the ``execute-sql`` query that retrieves response text. Errored calls count
    because this scorer is about scoping the attempt, not query success.
    """

    _label: str

    def __init__(self, *, name: str = "survey_id_used"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        seed = _survey_seed(output)
        if seed is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No survey_analysis seed on output"})

        survey_id = seed.get("survey_id")
        if not isinstance(survey_id, str) or not survey_id:
            return Score(name=self._name(), score=None, metadata={"reason": "No seeded survey_id"})

        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        matching_tools = [call.name for call in parser.get_tool_calls() if _contains_string(call.input, survey_id)]
        if matching_tools:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"survey_id": survey_id, "matched_tools": sorted(set(matching_tools))},
            )

        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Seeded survey ID was not found in any tool input",
                "survey_id": survey_id,
            },
        )


class SurveyResponseRetrieval(JudgedScorer):
    """Graded score: did the agent retrieve the seeded survey's open-ended responses via MCP SQL?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        executed = extract_last_execute_sql_call(output)
        if executed is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran execute-sql successfully"},
            )

        seed = _survey_seed(output)
        if seed is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No survey_analysis seed on output"})

        expected_payload = _expected_analysis(expected)
        if expected_payload is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No expected.survey_analysis provided"})

        return {
            "output": {
                "prompt": user_prompt(output),
                "sql_query": executed["query"],
                "sql_result": _truncate_for_judge(executed["result"]),
            },
            "expected": {
                "survey": seed,
                "analysis": expected_payload,
            },
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_response_retrieval",
            prompt_template="""
You are judging whether an agent successfully retrieved open-ended survey responses from PostHog using HogQL.

The eval seeded one survey and a known set of "survey sent" events. The agent's final successful `execute-sql` call should retrieve response text for that seeded survey, not just survey metadata or aggregate counts.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Seeded survey and expected responses:
<seeded_survey>
{{expected.survey}}
</seeded_survey>

Expected analysis shape:
<expected_analysis>
{{expected.analysis}}
</expected_analysis>

Executed HogQL:
<executed_query>
{{output.sql_query}}
</executed_query>

SQL result:
<sql_result>
{{output.sql_result}}
</sql_result>

Material requirements:
1. The query must target the seeded survey, either by its survey ID or by first resolving the named survey and then filtering responses to that survey.
2. The query must read actual open-ended response text from `survey sent` events. Strong signals include `getSurveyResponse(...)`, `$survey_response`, or `$survey_response_<question id/index>` fields.
3. The query result must contain enough response text to support analysis across the seeded questions. Aggregate-only counts are not sufficient.
4. It is acceptable for the query to retrieve question text/IDs from `system.surveys` in an earlier query, but this final judged query needs to expose the response text.
5. Minor SQL differences, ordering, aliases, or limits are fine if they do not materially omit the seeded response data.

Penalize heavily when:
- The query only calls `survey-stats`, only counts responses, or only lists the survey.
- The query fetches responses for a different survey.
- The query ignores multiple questions when the seeded survey has multiple open-ended questions.
""".strip()
            + "\n\n"
            + GRADED_ALIGNMENT_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )


class SurveyAnalysisAnswerAlignment(JudgedScorer):
    """Graded score: did the final answer analyze the retrieved survey responses?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        final_message = _final_message(output)
        if final_message is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message found"})

        executed = extract_last_execute_sql_call(output)
        if executed is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never ran execute-sql successfully"},
            )

        seed = _survey_seed(output)
        if seed is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No survey_analysis seed on output"})

        expected_payload = _expected_analysis(expected)
        if expected_payload is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No expected.survey_analysis provided"})

        return {
            "output": {
                "prompt": user_prompt(output),
                "sql_query": executed["query"],
                "sql_result": _truncate_for_judge(executed["result"]),
                "final_message": final_message,
            },
            "expected": {
                "survey": seed,
                "analysis": expected_payload,
            },
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_analysis_answer_alignment",
            prompt_template="""
You are judging an agent's final survey-analysis answer.

The agent was asked to analyze actual open-ended responses for a seeded survey. Judge whether the final answer faithfully analyzes the retrieved responses and covers the same intent as the expected analysis.

User prompt:
<user_prompt>
{{output.prompt}}
</user_prompt>

Seeded survey and response text:
<seeded_survey>
{{expected.survey}}
</seeded_survey>

Expected analysis:
<expected_analysis>
{{expected.analysis}}
</expected_analysis>

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

Material requirements:
1. The answer should identify the total open-ended response count or otherwise make clear it analyzed the expected volume of responses.
2. It should name key themes that align with the expected themes. Exact wording is not required.
3. It should state an overall sentiment consistent with the seeded responses.
4. It should provide actionable insights or recommendations grounded in the responses.
5. For placeholder/test-data cases, it should recognize that the responses are not meaningful product feedback and avoid inventing product conclusions.
6. For multi-question cases, it should reflect both questions rather than collapsing everything into one side of the feedback.

Penalize:
- Fabricated themes, counts, or recommendations not supported by the seeded response text.
- An answer that only describes how to query data without analyzing the responses.
- Overlooking an entire major theme or question from the expected analysis.
""".strip()
            + "\n\n"
            + GRADED_ALIGNMENT_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )
