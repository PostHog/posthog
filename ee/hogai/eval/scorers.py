import json
from typing import TypedDict

from autoevals.llm import LLMClassifier
from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import Score
from langchain_core.messages import AIMessage as LangchainAIMessage

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantTrendsQuery,
    NodeKind,
)


class ToolRelevance(ScorerWithPartial):
    semantic_similarity_args: set[str]

    def __init__(self, *, semantic_similarity_args: set[str]):
        self.semantic_similarity_args = semantic_similarity_args

    def _run_eval_sync(self, output, expected, **kwargs):
        if expected is None:
            return Score(name=self._name(), score=1 if not output or not output.tool_calls else 0)
        if output is None:
            return Score(name=self._name(), score=0)
        if not isinstance(expected, AssistantToolCall):
            raise TypeError(f"Eval case expected must be an AssistantToolCall, not {type(expected)}")
        if not isinstance(output, AssistantMessage | LangchainAIMessage):
            raise TypeError(f"Eval case output must be an AssistantMessage, not {type(output)}")
        if output.tool_calls and len(output.tool_calls) > 1:
            raise ValueError("Parallel tool calls not supported by this scorer yet")
        score = 0.0  # 0.0 to 1.0
        if output.tool_calls and len(output.tool_calls) == 1:
            tool_call = output.tool_calls[0]
            # 0.5 point for getting the tool right
            if tool_call.name == expected.name:
                score += 0.5
                if not expected.args:
                    score += 0.5 if not tool_call.args else 0  # If no args expected, only score for lack of args
                else:
                    score_per_arg = 0.5 / len(expected.args)
                    for arg_name, expected_arg_value in expected.args.items():
                        if arg_name in self.semantic_similarity_args:
                            arg_similarity = AnswerSimilarity(model="text-embedding-3-small").eval(
                                output=tool_call.args.get(arg_name), expected=expected_arg_value
                            )
                            score += arg_similarity.score * score_per_arg
                        elif tool_call.args.get(arg_name) == expected_arg_value:
                            score += score_per_arg
        return Score(name=self._name(), score=score)


class PlanAndQueryOutput(TypedDict):
    plan: str | None
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
    query_generation_retry_count: int | None


def serialize_output(output: PlanAndQueryOutput | dict | None) -> PlanAndQueryOutput | None:
    if output:
        return {
            **output,
            "query": output.get("query").model_dump(exclude_none=True),
        }
    return None


class QueryKindSelection(ScorerWithPartial):
    """Evaluate if the generated plan is of the correct type."""

    _expected: NodeKind

    def __init__(self, expected: NodeKind, **kwargs):
        super().__init__(**kwargs)
        self._expected = expected

    def _run_eval_sync(self, output: PlanAndQueryOutput, expected=None, **kwargs):
        if not output.get("query"):
            return Score(name=self._name(), score=None, metadata={"reason": "No query present"})
        score = 1 if output["query"].kind == self._expected else 0
        return Score(
            name=self._name(),
            score=score,
            metadata={"reason": f"Expected {self._expected}, got {output['query'].kind}"} if not score else {},
        )


class PlanCorrectness(LLMClassifier):
    """Evaluate if the generated plan correctly answers the user's question."""

    async def _run_eval_async(self, output: PlanAndQueryOutput, expected=None, **kwargs):
        if not output.get("plan"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No plan present"})
        output = PlanAndQueryOutput(
            plan=output.get("plan"),
            query=output["query"].model_dump_json(exclude_none=True) if output.get("query") else None,  # Clean up
        )
        return await super()._run_eval_async(output, serialize_output(expected), **kwargs)

    def _run_eval_sync(self, output: PlanAndQueryOutput, expected=None, **kwargs):
        if not output.get("plan"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No plan present"})
        output = PlanAndQueryOutput(
            plan=output.get("plan"),
            query=output["query"].model_dump_json(exclude_none=True) if output.get("query") else None,  # Clean up
        )
        return super()._run_eval_sync(output, serialize_output(expected), **kwargs)

    def __init__(self, query_kind: NodeKind, evaluation_criteria: str, **kwargs):
        super().__init__(
            name="plan_correctness",
            prompt_template="""
You will be given expected and actual generated plans to provide a taxonomy to answer the user's question with a {{query_kind}} insight.
By taxonomy, we mean the set of events, actions, math operations, property filters, cohort filters, and other project-specific elements that are used to answer the question.

Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan.
Do not apply general knowledge about {{query_kind}} insights.

<evaluation_criteria>
{{evaluation_criteria}}
</evaluation_criteria>

<input_vs_output>
User question:
<user_question>
{{input}}
</user_question>

Expected plan:
<expected_plan>
{{expected.plan}}
</expected_plan>

Actual generated plan:
<output_plan>
{{output.plan}}
</output_plan>

</input_vs_output>

How would you rate the correctness of the plan? Choose one:
- perfect: The plan fully matches the expected plan and addresses the user question.
- near_perfect: The plan mostly matches the expected plan with at most one immaterial detail missed from the user question.
- slightly_off: The plan mostly matches the expected plan with minor discrepancies.
- somewhat_misaligned: The plan has some correct elements but misses key aspects of the expected plan or question.
- strongly_misaligned: The plan does not match the expected plan or fails to address the user question.
- useless: The plan is incomprehensible.

Details matter greatly here - including math types or property types - so be harsh.
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            query_kind=query_kind,
            evaluation_criteria=evaluation_criteria,
            **kwargs,
        )


class QueryAndPlanAlignment(LLMClassifier):
    """Evaluate if the generated SQL query aligns with the plan generated in the previous step."""

    async def _run_eval_async(self, output: PlanAndQueryOutput, expected: PlanAndQueryOutput | None = None, **kwargs):
        if not output.get("plan"):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No plan present in the first place, skipping evaluation"},
            )
        if not output.get("query"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Query failed to be generated"})
        output = PlanAndQueryOutput(
            plan=output.get("plan"),
            query=output["query"].model_dump_json(exclude_none=True) if output.get("query") else None,  # Clean up
        )
        return await super()._run_eval_async(output, serialize_output(expected), **kwargs)

    def _run_eval_sync(self, output: PlanAndQueryOutput, expected: PlanAndQueryOutput | None = None, **kwargs):
        if not output.get("plan"):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No plan present in the first place, skipping evaluation"},
            )
        if not output.get("query"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Query failed to be generated"})
        output = PlanAndQueryOutput(
            plan=output.get("plan"),
            query=output["query"].model_dump_json(exclude_none=True) if output.get("query") else None,  # Clean up
        )
        return super()._run_eval_sync(output, serialize_output(expected), **kwargs)

    def __init__(self, query_kind: NodeKind, json_schema: dict, evaluation_criteria: str, **kwargs):
        json_schema_str = json.dumps(json_schema)
        if len(json_schema_str) > 100_000:
            raise ValueError(
                f"JSON schema of {query_kind} has blown up in size, are you sure you want to put this into an LLM? "
                "You CAN increase this limit if you're sure"
            )
        super().__init__(
            name="query_and_plan_alignment",
            prompt_template="""
Evaluate if the generated {{query_kind}} aligns with the query plan.

Use knowledge of the {{query_kind}} schema, especially included descriptions:
<json_schema>
{{json_schema}}
</json_schema>

<evaluation_criteria>
{{evaluation_criteria}}

Note: It's fine to include filterTestAccounts or showLegend in the query by default.
</evaluation_criteria>

<input_vs_output>
Original user question, only for context:
<user_question>
{{input}}
</user_question>

Generated query plan:
<plan>
{{output.plan}}
</plan>

Expected query based on the plan:
<expected_query>
{{expected.query}}
</expected_query>

Actual generated query:
<output_query>
{{output.query}}
</output_query>
</input_vs_output>

How would you rate the alignment of the generated query with the plan? Choose one:
- perfect: The generated query fully matches the plan.
- near_perfect: The generated query matches the plan with at most one immaterial detail missed from the user question.
- slightly_off: The generated query mostly matches the plan, with minor discrepancies that may slightly change the meaning of the query.
- somewhat_misaligned: The generated query has some correct elements, but misses key aspects of the plan.
- strongly_misaligned: The generated query does not match the plan and fails to address the user question.
- useless: The generated query is basically incomprehensible.

Details matter greatly here - including math types or property types - so be harsh.""".strip(),
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            query_kind=query_kind,
            json_schema=json_schema_str,
            evaluation_criteria=evaluation_criteria,
            max_tokens=1024,
            **kwargs,
        )


class TimeRangeRelevancy(LLMClassifier):
    """Evaluate if the generated query's time range, interval, or period correctly answers the user's question."""

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("query"):
            return Score(name=self._name(), score=None, metadata={"reason": "No query to check, skipping evaluation"})
        return await super()._run_eval_async(output, serialize_output(expected), **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("query"):
            return Score(name=self._name(), score=None, metadata={"reason": "No query to check"})
        return super()._run_eval_sync(output, serialize_output(expected), **kwargs)

    def __init__(self, query_kind: NodeKind, **kwargs):
        super().__init__(
            name="time_range_relevancy",
            prompt_template="""You will be given an original user question and the generated query (or query components) to answer that question.
Your goal is to determine if the time range, interval, or period in the generated query is relevant and correct based on the user's question.

<evaluation_criteria>
1. Explicit Time Mentions: If the user's question explicitly mentions a time range (e.g., "last 7 days", "this month", "January 2023", "before 2024-01-01"), the query MUST reflect this.
    - For "last X days/weeks/months": Check if the query uses a relative date range (e.g., -Xd, -Xw, -Xm or `now() - interval 'X day/week/month'`).
    - For "this month/year": Check if the query filters for the current month/year (e.g., `date_trunc('month', timestamp) = date_trunc('month', now())`).
    - For specific dates or months (e.g., "January 2023", "this January"): Check if the query filters for the exact date or month and year.
2. Implicit Time Context: If the user's question implies a time context without being explicit (e.g., "recent activity", "trends over time"), the query should use a reasonable default time range (e.g., last 30 days, last 7 days) or an appropriate interval/period.
3. Interval/Period Correctness (for Trends, Retention, HogQL):
    - Trends: If the question implies a specific granularity (e.g., "daily pageviews for the last 80 days" implies 'week' or 'day' interval, "pageviews over last five years" implies 'month' interval), the `interval` field in the query should match.
    - Retention: If the question implies a cohort period (e.g., "daily retention", "weekly cohort"), the `period` field should match (e.g., "Day", "Week").
    - HogQL: If the question implies aggregation over time periods (e.g. "average session duration by day of week"), check for appropriate time functions like `dayOfWeek` or `toStartOfWeek`.
4. No Time Mention: If the user's question has no discernible time component, the query can use a default time range, or no time filter if not applicable, and should not be penalized.
5. Excessive or Missing Time Filters: Penalize if the query includes time filters that contradict the user's question or omits them when clearly needed. For SQL, check if `timestamp` or relevant date fields are used in WHERE clauses for filtering.

Query type specific considerations for `output.query`:
- HogQL: `output.query` is an AssistantHogQLQuery object. The actual SQL string is in `output.query.query`. (HogQL is a flavor of standard SQL.)
- Trends: `output.query` is an AssistantTrendsQuery object. Check `output.query.dateRange` and `output.query.interval`.
- Funnels: `output.query` is an AssistantFunnelsQuery object. Check `output.query.dateRange`. Funnels do not have an interval.
- Retention: `output.query` is an AssistantRetentionQuery object. Check `output.query.dateRange` and `output.query.retentionFilter.period`.
</evaluation_criteria>

<input_vs_output>

User question:
<user_question>
{{input}}
</user_question>

Generated {{query_kind}} query components:
<output_query>
{{output.query}}
</output_query>

</input_vs_output>

How would you rate the time range relevancy of the generated query? Choose one:
- perfect: The time range, interval, and/or period in the query perfectly match the user's question or a sensible default if unspecified.
- near_perfect: The query's time components mostly match the user's question with at most one immaterial detail missed or slightly off.
- slightly_off: The query's time components have minor discrepancies that might slightly alter the insight but generally align with the question.
- somewhat_misaligned: The query's time components have some correct elements but miss key aspects of the question's time requirements or use inappropriate defaults.
- strongly_misaligned: The query's time components do not match the question's time requirements at all.
- not_applicable: The user's question has no time component, and the query correctly omits time filters or uses a broad default that doesn't interfere.
- useless: The query's time components are incomprehensible or completely wrong.
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "not_applicable": 1.0,
                "useless": 0.0,
            },
            model="gpt-4.1",
            query_kind=query_kind,
            **kwargs,
        )
