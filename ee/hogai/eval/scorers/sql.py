from typing import Any

from asgiref.sync import sync_to_async
from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from posthog.hogql.errors import BaseHogQLError

from posthog.errors import InternalCHQueryError
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.team.team import Team


def evaluate_sql_query(name: str, output: str | None, team: Team | None = None) -> Score:
    if not output:
        return Score(name=name, score=None, metadata={"reason": "No SQL query to verify, skipping evaluation"})
    if not team:
        return Score(name=name, score=None, metadata={"reason": "No team provided, skipping evaluation"})
    query = {"query": output}
    try:
        # Try to parse, print, and run the query
        HogQLQueryRunner(query, team).calculate()
    except BaseHogQLError as e:
        return Score(name=name, score=0.0, metadata={"reason": f"HogQL-level error: {str(e)}"})
    except InternalCHQueryError as e:
        return Score(name=name, score=0.5, metadata={"reason": f"ClickHouse-level error: {str(e)}"})
    else:
        return Score(name=name, score=1.0)


class SQLSyntaxCorrectness(Scorer):
    """Evaluate if the generated SQL query has correct syntax."""

    def _name(self):
        return "sql_syntax_correctness"

    async def _run_eval_async(self, output: str | None, expected: Any = None, team: Team | None = None, **kwargs):
        return await sync_to_async(self._evaluate)(output, team)

    def _run_eval_sync(self, output: str | None, expected: Any = None, team: Team | None = None, **kwargs):
        return self._evaluate(output, team)

    def _evaluate(self, output: str | None, team: Team | None = None) -> Score:
        return evaluate_sql_query(self._name(), output, team)


SQL_SEMANTICS_CORRECTNESS_PROMPT = """
<system>
You are an expert ClickHouse SQL auditor.
Your job is to decide whether two ClickHouse SQL queries are **semantically equivalent for every possible valid database state**, given the same task description and schema.

When you respond, think step-by-step **internally**, but reveal **nothing** except the final verdict:
• Output **Pass** if the candidate query would always return the same result set (ignoring column aliases, ordering, or trivial formatting) as the reference query.
• Output **Fail** otherwise, or if you are uncertain.
Respond with a single word—**Pass** or **Fail**—and no additional text.
</system>

<input>
Task / natural-language question:
```
{{input}}
```

Database schema (tables and columns):
```
{{database_schema}}
```

Reference (human-labelled) SQL:
```sql
{{expected}}
```

Candidate (generated) SQL:
```sql
{{output}}
```
</input>

<reminder>
Think through edge cases: NULL handling, grouping, filters, joins, HAVING clauses, aggregations, sub-queries, limits, and data-type quirks.
If any logical difference could yield different outputs under some data scenario, the queries are *not* equivalent.
</reminder>

When ready, output your verdict—**Pass** or **Fail**—with absolutely no extra characters.
""".strip()


class SQLSemanticsCorrectness(LLMClassifier):
    """Evaluate if the actual query matches semantically the expected query."""

    def __init__(self, **kwargs):
        super().__init__(
            name="sql_semantics_correctness",
            prompt_template=SQL_SEMANTICS_CORRECTNESS_PROMPT,
            choice_scores={
                "Pass": 1.0,
                "Fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(
        self, output: str | None, expected: str | None = None, database_schema: str | None = None, **kwargs
    ):
        if not output or output.strip() == "":
            return Score(name=self._name(), score=None, metadata={"reason": "No query to check, skipping evaluation"})
        return await super()._run_eval_async(output, expected, database_schema=database_schema, **kwargs)

    def _run_eval_sync(
        self, output: str | None, expected: str | None = None, database_schema: str | None = None, **kwargs
    ):
        if not output or output.strip() == "":
            return Score(name=self._name(), score=None, metadata={"reason": "No query to check, skipping evaluation"})
        return super()._run_eval_sync(output, expected, database_schema=database_schema, **kwargs)
