import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from django.conf import settings

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.database.models import DANGEROUS_NoTeamIdCheckTable, DatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.functions.prompt_jev import MODEL, PromptJevCall, PromptJevFinder
from posthog.hogql.type_system import constant_type_from_runtime_type, parse_clickhouse_type
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
)
from posthog.llm.system_one_client import SystemOneClient, build_system_one_client

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

MAX_ROWS = 1000
MAX_INPUT_BYTES = 8192
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_BATCH_BYTES = 32768


class _ResultField(DatabaseField):
    clickhouse_type: str

    def get_constant_type(self) -> ast.ConstantType:
        return constant_type_from_runtime_type(parse_clickhouse_type(self.clickhouse_type))


class _ResultTable(DANGEROUS_NoTeamIdCheckTable):
    # These rows have already passed the source query's tenant and resource access checks.
    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return escape_clickhouse_identifier(self.name or "")

    def to_printed_hogql(self) -> str:
        return self.name or ""


@frozen
class PromptJevTable:
    name: str
    structure: list[tuple[str, str]]
    rows: list[list[object]]

    def register(self, context: "HogQLContext") -> None:
        assert context.database is not None
        context.external_tables[self.name] = {
            "name": self.name,
            "structure": self.structure,
            "data": [dict(zip((name for name, _ in self.structure), row)) for row in self.rows],
        }
        context.database.tables.add_child(
            TableNode(
                name=self.name,
                table=_ResultTable(
                    name=self.name,
                    fields={name: _ResultField(name=name, clickhouse_type=kind) for name, kind in self.structure},
                ),
                hidden=True,
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )


@frozen
class _DecisionKey:
    question: str
    text: str


class PromptJevRunner:
    def __init__(self, *, team_id: int, distinct_id: str | None) -> None:
        self.team_id = team_id
        self.distinct_id = distinct_id
        self.cache: dict[_DecisionKey, object] = {}
        self.input_bytes = 0
        self.deadline = time.monotonic() + 60
        self.client: SystemOneClient | None = None

    def _batch(self, spec: PromptJevCall, texts: list[str]) -> dict[str, object]:
        assert self.client is not None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise QueryError("prompt_jev exceeded its time limit. Select fewer rows and try again.")
        questions: dict[str, Question] = {}
        state: dict[str, str] = {}
        for i, text in enumerate(texts):
            key = f"row_{i}"
            state[key] = text
            questions[key] = replace(
                spec.question,
                instructions={
                    "input": f"Evaluate only the text in state.{key}.",
                    "question": spec.question.instructions,
                },
            )
        try:
            result = replace(self.client, timeout=min(remaining, 30)).decide(state=state, questions=questions)
        except SystemOneRequestFailed as error:
            raise QueryError("Jev could not evaluate this query. Try again or select fewer rows.") from error
        decisions: dict[str, object] = {}
        for key, text in state.items():
            answer = result.answers[key]
            if isinstance(answer, NoulAnswer):
                decisions[text] = answer.probability
            elif isinstance(answer, ChoiceAnswer):
                decisions[text] = (answer.choice, list(answer.probabilities.items()), answer.confidence)
        return decisions

    def evaluate(self, spec: PromptJevCall, values: list[object]) -> list[object]:
        question_key = json.dumps(spec.question.to_json(), sort_keys=True)
        missing: dict[str, None] = {}
        for value in values:
            if value is None:
                continue
            if not isinstance(value, str):
                raise QueryError("prompt_jev input must be text. Use toString(input) to convert it.")
            if len(value.encode()) > MAX_INPUT_BYTES:
                raise QueryError("prompt_jev input exceeds 8 KiB. Shorten each input before classifying it.")
            if _DecisionKey(question=question_key, text=value) not in self.cache:
                missing[value] = None
        self.input_bytes += sum(len(text.encode()) for text in missing)
        if len(self.cache) + len(missing) > MAX_ROWS or self.input_bytes > MAX_TOTAL_BYTES:
            raise QueryError("prompt_jev exceeds the query budget. Select fewer or shorter inputs.")
        if missing and self.client is None:
            try:
                self.client = build_system_one_client(
                    model=MODEL,
                    ai_product="hogql_prompt_jev",
                    distinct_id=self.distinct_id,
                    properties={"team_id": str(self.team_id)},
                )
            except SystemOneNotConfigured as error:
                raise QueryError(
                    "Jev is not configured. Set AI_GATEWAY_URL and AI_GATEWAY_API_KEY on the server."
                ) from error
        batches: list[list[str]] = []
        batch_bytes = 0
        for text in missing:
            size = len(text.encode())
            if not batches or len(batches[-1]) >= spec.batch_size or batch_bytes + size > MAX_BATCH_BYTES:
                batches.append([])
                batch_bytes = 0
            batches[-1].append(text)
            batch_bytes += size
        with ThreadPoolExecutor(max_workers=4) as pool:
            for decisions in pool.map(lambda batch: self._batch(spec, batch), batches):
                for text, decision in decisions.items():
                    self.cache[_DecisionKey(question=question_key, text=text)] = decision
        null: object = (None, [], None) if isinstance(spec.question, ChoiceQuestion) else None
        return [
            null if value is None else self.cache[_DecisionKey(question=question_key, text=cast(str, value))]
            for value in values
        ]


class _LocalFinder(PromptJevFinder):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass


class _AliasReferences(TraversingVisitor):
    def __init__(self, aliases: set[str]) -> None:
        self.aliases = aliases

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self.aliases:
            raise QueryError("Read prompt_jev result aliases from an outer query.")


class PromptJevPlanner(CloningVisitor):
    def __init__(
        self,
        *,
        execute: Callable[[ast.SelectQuery], HogQLQueryResponse],
        runner: PromptJevRunner,
        tables: list[PromptJevTable],
    ) -> None:
        super().__init__(clear_types=True)
        self.execute = execute
        self.runner = runner
        self.tables = tables
        self.ctes: dict[str, ast.CTE] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        previous = self.ctes
        self.ctes = dict(previous)
        try:
            for name, cte in (node.ctes or {}).items():
                self.ctes[name] = self.visit(cte)
            without_ctes = clone_expr(node)
            without_ctes.ctes = None
            query = cast(ast.SelectQuery, super().visit_select_query(without_ctes))
            query.ctes = dict(self.ctes) or None
            local = _LocalFinder()
            for column in query.select:
                local.visit(column)
            if not local.calls:
                return query
            if (
                query.distinct
                or query.group_by
                or query.group_by_mode
                or query.having
                or query.qualify
                or query.order_by
                or query.limit_by
                or query.limit_percent
                or query.limit_with_ties
            ):
                raise QueryError("Apply grouping, sorting, and DISTINCT in a query outside the prompt_jev SELECT.")
            specs: dict[int, PromptJevCall] = {}
            aliases: set[str] = set()
            for i, column in enumerate(query.select):
                if (
                    isinstance(column, ast.Alias)
                    and isinstance(column.expr, ast.Call)
                    and column.expr.name.lower() == "prompt_jev"
                ):
                    specs[i] = PromptJevCall.parse(column.expr)
                    aliases.add(column.alias)
                elif isinstance(column, ast.Field) and "*" in column.chain:
                    raise QueryError("List columns explicitly in a prompt_jev SELECT instead of using '*'.")
            if len(specs) != len(local.calls):
                raise QueryError("Use prompt_jev as a named SELECT column, then read it from an outer query.")
            source = clone_expr(query)
            for i, spec in specs.items():
                source.select[i] = ast.Alias(alias=cast(ast.Alias, query.select[i]).alias, expr=clone_expr(spec.input))
            if PromptJevFinder.contains(source):
                raise QueryError("Use prompt_jev only in SELECT columns. Filter its results in an outer query.")
            _AliasReferences(aliases).visit(source)
            if source.limit is None:
                source.limit = ast.Constant(value=MAX_ROWS + 1)
            elif (
                not isinstance(source.limit, ast.Constant)
                or type(source.limit.value) is not int
                or not 0 <= source.limit.value <= MAX_ROWS
            ):
                raise QueryError(f"prompt_jev LIMIT must be an integer literal between 0 and {MAX_ROWS}.")
            response = self.execute(source)
            if response.error:
                raise QueryError(response.error)
            rows: list[list[object]] = [list(row) for row in response.results or []]
            if len(rows) > MAX_ROWS:
                raise QueryError(f"prompt_jev reads at most {MAX_ROWS} rows. Add a LIMIT to its SELECT.")
            names = response.columns or []
            if len(names) != len(query.select) or len(set(names)) != len(names):
                raise QueryError("Give each column in the prompt_jev SELECT a unique name.")
            structure = [(str(name), str(kind)) for name, kind in response.types or []]
            for i, spec in specs.items():
                values = self.runner.evaluate(spec, [row[i] for row in rows])
                for row, value in zip(rows, values):
                    row[i] = value
                structure[i] = (names[i], spec.clickhouse_type)
            structure = [(name, structure[i][1]) for i, name in enumerate(names)]
            table = PromptJevTable(name=f"__prompt_jev_{uuid.uuid4().hex}", structure=structure, rows=rows)
            self.tables.append(table)
            return ast.SelectQuery(
                select=[ast.Field(chain=[name]) for name in names],
                select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
            )
        finally:
            self.ctes = previous

    def visit_call(self, node: ast.Call) -> ast.Call:
        # Binding validates every call, including ones whose SELECT has no rows.
        if node.name.lower() == "prompt_jev":
            PromptJevCall.parse(node)
        return cast(ast.Call, super().visit_call(node))


def validate_prompt_jev_enabled() -> None:
    if not settings.HOGQL_PROMPT_JEV_ENABLED:
        raise QueryError("prompt_jev is disabled. Ask your administrator to enable HOGQL_PROMPT_JEV_ENABLED.")
