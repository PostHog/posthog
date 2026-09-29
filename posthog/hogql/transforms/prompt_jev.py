import json
import time
import uuid
import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from django.conf import settings

from asgiref.sync import async_to_sync

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
from posthog.llm.system_one_client import GatewaySystemOneClient, build_system_one_client
from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

    from posthog.models.team import Team

MAX_ROWS = 1000
MAX_DECISIONS = 1000
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
        self.client: GatewaySystemOneClient | None = None

    async def _batch(self, spec: PromptJevCall, texts: list[str]) -> dict[str, object]:
        assert self.client is not None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise QueryError("__preview_promptJev exceeded its time limit. Select fewer rows and try again.")
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
            result = await replace(self.client, timeout=min(remaining, 30)).adecide(state=state, questions=questions)
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

    async def _batches(self, spec: PromptJevCall, batches: list[list[str]]) -> list[dict[str, object]]:
        semaphore = asyncio.Semaphore(4)

        async def evaluate_batch(batch: list[str]) -> dict[str, object]:
            async with semaphore:
                return await self._batch(spec, batch)

        tasks: list[asyncio.Task[dict[str, object]]] = []
        try:
            async with asyncio.timeout(max(0, self.deadline - time.monotonic())):
                tasks = [asyncio.create_task(evaluate_batch(batch)) for batch in batches]
                return await asyncio.gather(*tasks)
        except TimeoutError as error:
            raise QueryError("__preview_promptJev exceeded its time limit. Select fewer rows and try again.") from error
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def evaluate(self, spec: PromptJevCall, values: list[object]) -> list[object]:
        question_key = json.dumps(spec.question.to_json(), sort_keys=True)
        missing: dict[str, None] = {}
        for value in values:
            if value is None:
                continue
            if not isinstance(value, str):
                raise QueryError("__preview_promptJev input must be text. Use toString(input) to convert it.")
            if len(value.encode()) > MAX_INPUT_BYTES:
                raise QueryError("__preview_promptJev input exceeds 8 KiB. Shorten each input before classifying it.")
            if _DecisionKey(question=question_key, text=value) not in self.cache:
                missing[value] = None
        self.input_bytes += sum(len(text.encode()) for text in missing)
        if len(self.cache) + len(missing) > MAX_DECISIONS or self.input_bytes > MAX_TOTAL_BYTES:
            raise QueryError("__preview_promptJev exceeds the query budget. Select fewer or shorter inputs.")
        if missing and self.client is None:
            try:
                client = build_system_one_client(
                    model=MODEL,
                    ai_product="hogql_prompt_jev",
                    distinct_id=self.distinct_id,
                    properties={"team_id": str(self.team_id)},
                )
                assert isinstance(client, GatewaySystemOneClient)
                self.client = client
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
        if batches:
            for decisions in async_to_sync(self._batches)(spec, batches):
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


class PromptJevBudget(TraversingVisitor):
    def __init__(self) -> None:
        self.decisions = 0

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        finder = _LocalFinder()
        for column in node.select:
            finder.visit(column)
        if finder.calls:
            rows = MAX_ROWS
            if node.limit is not None:
                if (
                    not isinstance(node.limit, ast.Constant)
                    or type(node.limit.value) is not int
                    or not 0 <= node.limit.value <= MAX_ROWS
                ):
                    raise QueryError(f"__preview_promptJev LIMIT must be an integer literal between 0 and {MAX_ROWS}.")
                rows = node.limit.value
            # Reserve the worst case before any stage runs, including stages that depend on earlier decisions.
            self.decisions += rows * len(finder.calls)
            if self.decisions > MAX_DECISIONS:
                raise QueryError(
                    f"__preview_promptJev allows at most {MAX_DECISIONS} row evaluations across all columns and SELECTs. "
                    f"This query reserves {self.decisions}. Add smaller LIMITs to the SELECTs containing Jev calls, "
                    "or use fewer Jev columns. A SELECT without LIMIT reserves 1000 rows per Jev column."
                )
        super().visit_select_query(node)


class _AliasReferences(TraversingVisitor):
    def __init__(self, aliases: set[str]) -> None:
        self.aliases = aliases

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self.aliases:
            raise QueryError("Read __preview_promptJev result aliases from an outer query.")


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
                raise QueryError(
                    "Apply grouping, sorting, and DISTINCT in a query outside the __preview_promptJev SELECT."
                )
            specs: dict[int, PromptJevCall] = {}
            aliases: set[str] = set()
            for i, column in enumerate(query.select):
                if (
                    isinstance(column, ast.Alias)
                    and isinstance(column.expr, ast.Call)
                    and column.expr.name.lower() == "__preview_promptjev"
                ):
                    specs[i] = PromptJevCall.parse(column.expr)
                    aliases.add(column.alias)
                elif isinstance(column, ast.Field) and "*" in column.chain:
                    raise QueryError("List columns explicitly in a __preview_promptJev SELECT instead of using '*'.")
            if len(specs) != len(local.calls):
                raise QueryError("Use __preview_promptJev as a named SELECT column, then read it from an outer query.")
            source = clone_expr(query)
            for i, spec in specs.items():
                source.select[i] = ast.Alias(alias=cast(ast.Alias, query.select[i]).alias, expr=clone_expr(spec.input))
            if PromptJevFinder.contains(source):
                raise QueryError(
                    "Use __preview_promptJev only in SELECT columns. Filter its results in an outer query."
                )
            _AliasReferences(aliases).visit(source)
            if source.limit is None:
                source.limit = ast.Constant(value=MAX_ROWS + 1)
            elif (
                not isinstance(source.limit, ast.Constant)
                or type(source.limit.value) is not int
                or not 0 <= source.limit.value <= MAX_ROWS
            ):
                raise QueryError(f"__preview_promptJev LIMIT must be an integer literal between 0 and {MAX_ROWS}.")
            response = self.execute(source)
            if response.error:
                raise QueryError(response.error)
            rows: list[list[object]] = [list(row) for row in response.results or []]
            if len(rows) > MAX_ROWS:
                raise QueryError(f"__preview_promptJev reads at most {MAX_ROWS} rows. Add a LIMIT to its SELECT.")
            names = response.columns or []
            if len(names) != len(query.select) or len(set(names)) != len(names):
                raise QueryError("Give each column in the __preview_promptJev SELECT a unique name.")
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
        if node.name.lower() == "__preview_promptjev":
            PromptJevCall.parse(node)
        return cast(ast.Call, super().visit_call(node))


def validate_prompt_jev_access(team: "Team") -> None:
    if settings.CLICKHOUSE_USE_HTTP or team.pk in settings.CLICKHOUSE_USE_HTTP_PER_TEAM:
        raise QueryError(
            "__preview_promptJev requires the native ClickHouse connection. Ask your administrator to configure it."
        )
    if not feature_enabled_or_false(
        "hogql-prompt-jev",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.pk)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.pk)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    ):
        raise QueryError("__preview_promptJev is not enabled for this project. Contact support to request access.")
