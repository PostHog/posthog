import json
import math
import time
import uuid
import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.database.models import DANGEROUS_NoTeamIdCheckTable, DatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.functions.prompt_jev import PromptJevCall, PromptJevFinder
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

logger = structlog.get_logger(__name__)

MAX_ROWS = 1000
MAX_DECISIONS = 1000
MAX_INPUT_BYTES = 8192
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_BATCH_BYTES = 32768


class _ResultField(DatabaseField):
    clickhouse_type: str
    hogql_type: ast.ConstantType | None = None

    def get_constant_type(self) -> ast.ConstantType:
        if self.hogql_type is not None:
            return self.hogql_type
        return constant_type_from_runtime_type(parse_clickhouse_type(self.clickhouse_type))


class _ResultTable(DANGEROUS_NoTeamIdCheckTable):
    # These rows have already passed the source query's tenant and resource access checks.
    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return escape_clickhouse_identifier(self.name or "")

    def to_printed_hogql(self) -> str:
        return self.name or ""


@frozen
class PromptJevColumn:
    name: str
    clickhouse_type: str
    # A ClickHouse type does not say whether the source column was a JSON blob or an array, so a
    # passthrough column keeps its HogQL type here and an outer query can still read properties off it.
    hogql_type: ast.ConstantType | None = None


@frozen
class PromptJevSource:
    response: HogQLQueryResponse
    column_types: dict[str, ast.ConstantType]


@frozen
class PromptJevTable:
    name: str
    columns: list[PromptJevColumn]
    rows: list[list[object]]

    def register(self, context: "HogQLContext") -> None:
        assert context.database is not None
        names = [column.name for column in self.columns]
        context.external_tables[self.name] = {
            "name": self.name,
            "structure": [(column.name, column.clickhouse_type) for column in self.columns],
            "data": [dict(zip(names, row)) for row in self.rows],
        }
        context.database.tables.add_child(
            TableNode(
                name=self.name,
                table=_ResultTable(
                    name=self.name,
                    fields={
                        column.name: _ResultField(
                            name=column.name,
                            clickhouse_type=column.clickhouse_type,
                            hogql_type=column.hogql_type,
                        )
                        for column in self.columns
                    },
                ),
                hidden=True,
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )


OUT_OF_AI_CREDITS_MESSAGE = (
    "jev can't run because your organization has used all its AI credits. "
    "Add credits in billing settings, then try again."
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

    def source_timeout(self) -> int:
        # Source scans share the inference deadline. ClickHouse takes max_execution_time in whole seconds, and 0 disables it.
        return max(1, math.ceil(self.deadline - time.monotonic()))

    async def _batch(self, spec: PromptJevCall, texts: list[str]) -> dict[str, object]:
        assert self.client is not None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise QueryError("jev exceeded its time limit. Select fewer rows and try again.")
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
            # Log only the status, because the inputs and the gateway response body can hold customer data.
            logger.warning(
                "prompt_jev_gateway_failed",
                team_id=self.team_id,
                status_code=error.status_code,
                reason=type(error).__name__,
            )
            if error.status_code == 402:
                raise QueryError(OUT_OF_AI_CREDITS_MESSAGE) from error
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
            raise QueryError("jev exceeded its time limit. Select fewer rows and try again.") from error
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def check_budget(self, columns: list[tuple[PromptJevCall, list[object]]]) -> dict[_DecisionKey, None]:
        missing: dict[_DecisionKey, None] = {}
        for spec, values in columns:
            question_key = json.dumps(spec.question.to_json(), sort_keys=True)
            for value in values:
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise QueryError("jev input must be text. Use toString(input) to convert it.")
                if len(value.encode()) > MAX_INPUT_BYTES:
                    raise QueryError("jev input exceeds 8 KiB. Shorten each input before classifying it.")
                key = _DecisionKey(question=question_key, text=value)
                if key not in self.cache:
                    missing[key] = None
        input_bytes = self.input_bytes + sum(len(key.text.encode()) for key in missing)
        if len(self.cache) + len(missing) > MAX_DECISIONS or input_bytes > MAX_TOTAL_BYTES:
            raise QueryError("jev exceeds the query budget. Select fewer or shorter inputs.")
        return missing

    def evaluate(self, spec: PromptJevCall, values: list[object]) -> list[object]:
        question_key = json.dumps(spec.question.to_json(), sort_keys=True)
        missing = [key.text for key in self.check_budget([(spec, values)])]
        self.input_bytes += sum(len(text.encode()) for text in missing)
        if missing and self.client is None:
            try:
                client = build_system_one_client(
                    model=settings.HOGQL_PROMPT_JEV_MODEL,
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

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        initial = node.initial_select_query
        # A WITH clause on the first branch stays in scope for every later branch, so its CTEs are
        # counted once across the whole set. Counting them per branch reserves nothing for a CTE
        # that only a later branch reads, and the query then spends inference the budget never
        # approved.
        if not isinstance(initial, ast.SelectQuery) or not initial.ctes:
            super().visit_select_set_query(node)
            return
        without_ctes = clone_expr(node)
        cast(ast.SelectQuery, without_ctes.initial_select_query).ctes = None
        for cte in _CTEReferences.used(without_ctes, initial.ctes).values():
            self.visit(cte)
        super().visit_select_set_query(without_ctes)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        node = clone_expr(node)
        ctes = node.ctes or {}
        node.ctes = None
        node.ctes = _CTEReferences.used(node, ctes) or None
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
                    raise QueryError(f"jev LIMIT must be an integer literal between 0 and {MAX_ROWS}.")
                rows = node.limit.value
            # Reserve the worst case before any stage runs, including stages that depend on earlier decisions.
            self.decisions += rows * len(finder.calls)
            if self.decisions > MAX_DECISIONS:
                raise QueryError(
                    f"jev exceeds the query budget of {MAX_DECISIONS} row evaluations across all columns and SELECTs. "
                    f"This query reserves {self.decisions}. Add smaller LIMITs to the SELECTs containing Jev calls, "
                    "or use fewer Jev columns. A SELECT without LIMIT reserves 1000 rows per Jev column."
                )
        super().visit_select_query(node)


class _AliasReferences(TraversingVisitor):
    def __init__(self, aliases: set[str]) -> None:
        self.aliases = aliases
        self.in_scope = False

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self.aliases:
            raise QueryError("Read jev result aliases from an outer query.")

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # HogQL resolves a field only against its own SELECT, so fields in nested SELECTs cannot read these aliases.
        if not self.in_scope:
            self.in_scope = True
            super().visit_select_query(node)


class _CTEReferences(TraversingVisitor):
    def __init__(self) -> None:
        self.names: set[str | int] = set()

    def visit_field(self, node: ast.Field) -> None:
        self.names.update(node.chain[:1])

    @classmethod
    def used(cls, query: ast.Expr, ctes: dict[str, ast.CTE]) -> dict[str, ast.CTE]:
        # ClickHouse does not run a CTE that nothing reads, so inference must not run for it either.
        references = cls()
        references.visit(query)
        used: set[str] = set()
        while pending := [name for name in ctes if name in references.names and name not in used]:
            for name in pending:
                used.add(name)
                references.visit(ctes[name])
        return {name: cte for name, cte in ctes.items() if name in used}


class PromptJevPlanner(CloningVisitor):
    def __init__(
        self,
        *,
        execute: Callable[[ast.SelectQuery], PromptJevSource],
        runner: PromptJevRunner,
        tables: list[PromptJevTable],
    ) -> None:
        super().__init__(clear_types=True)
        self.execute = execute
        self.runner = runner
        self.tables = tables
        self.ctes: dict[str, ast.CTE] = {}

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        initial = node.initial_select_query
        # A WITH clause on the first branch stays in scope for every later branch, so its CTEs are
        # planned once across the whole set. Planning them per branch drops a CTE that only a later
        # branch reads, and that branch then cannot find its table.
        if not isinstance(initial, ast.SelectQuery) or not initial.ctes:
            return cast(ast.SelectSetQuery, super().visit_select_set_query(node))
        previous = self.ctes
        self.ctes = dict(previous)
        try:
            without_ctes = clone_expr(node)
            cast(ast.SelectQuery, without_ctes.initial_select_query).ctes = None
            for name, cte in _CTEReferences.used(without_ctes, initial.ctes).items():
                self.ctes[name] = self.visit(cte)
            return cast(ast.SelectSetQuery, super().visit_select_set_query(without_ctes))
        finally:
            self.ctes = previous

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        previous = self.ctes
        self.ctes = dict(previous)
        try:
            without_ctes = clone_expr(node)
            without_ctes.ctes = None
            for name, cte in _CTEReferences.used(without_ctes, node.ctes or {}).items():
                self.ctes[name] = self.visit(cte)
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
                raise QueryError("Apply grouping, sorting, and DISTINCT in a query outside the jev SELECT.")
            specs: dict[int, PromptJevCall] = {}
            aliases: set[str] = set()
            for i, column in enumerate(query.select):
                if (
                    isinstance(column, ast.Alias)
                    and isinstance(column.expr, ast.Call)
                    and column.expr.name.lower() == "jev"
                ):
                    specs[i] = PromptJevCall.parse(column.expr)
                    aliases.add(column.alias)
                elif isinstance(column, ast.Field) and "*" in column.chain:
                    raise QueryError("List columns explicitly in a jev SELECT instead of using '*'.")
            if len(specs) != len(local.calls):
                raise QueryError("Use jev as a named SELECT column, then read it from an outer query.")
            source = clone_expr(query)
            for i, spec in specs.items():
                source.select[i] = ast.Alias(alias=cast(ast.Alias, query.select[i]).alias, expr=clone_expr(spec.input))
            if PromptJevFinder.contains(source):
                raise QueryError("Use jev only in SELECT columns. Filter its results in an outer query.")
            _AliasReferences(aliases).visit(source)
            if source.limit is None:
                source.limit = ast.Constant(value=MAX_ROWS + 1)
            elif (
                not isinstance(source.limit, ast.Constant)
                or type(source.limit.value) is not int
                or not 0 <= source.limit.value <= MAX_ROWS
            ):
                raise QueryError(f"jev LIMIT must be an integer literal between 0 and {MAX_ROWS}.")
            result = self.execute(source)
            response = result.response
            if response.error:
                raise QueryError(response.error)
            rows: list[list[object]] = [list(row) for row in response.results or []]
            if len(rows) > MAX_ROWS:
                raise QueryError(f"jev reads at most {MAX_ROWS} rows. Add a LIMIT to its SELECT.")
            names = response.columns or []
            if len(names) != len(query.select) or len(set(names)) != len(names):
                raise QueryError("Give each column in the jev SELECT a unique name.")
            kinds = [str(kind) for _, kind in response.types or []]
            inputs = {i: [row[i] for row in rows] for i in specs}
            self.runner.check_budget([(spec, inputs[i]) for i, spec in specs.items()])
            for i, spec in specs.items():
                values = self.runner.evaluate(spec, inputs[i])
                for row, value in zip(rows, values):
                    row[i] = value
                kinds[i] = spec.clickhouse_type
            columns = [
                PromptJevColumn(
                    name=name,
                    clickhouse_type=kinds[i],
                    hogql_type=None if i in specs else result.column_types.get(name),
                )
                for i, name in enumerate(names)
            ]
            table = PromptJevTable(name=f"__prompt_jev_{uuid.uuid4().hex}", columns=columns, rows=rows)
            self.tables.append(table)
            return ast.SelectQuery(
                select=[ast.Field(chain=[name]) for name in names],
                select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
                # The source query consumed the LIMIT and the OFFSET. Keeping the limit stops the
                # default row limit from replacing it; re-applying the offset would skip rows twice.
                limit=clone_expr(query.limit) if query.limit is not None else None,
            )
        finally:
            self.ctes = previous

    def visit_call(self, node: ast.Call) -> ast.Call:
        # Binding validates every call, including ones whose SELECT has no rows.
        if node.name.lower() == "jev":
            PromptJevCall.parse(node)
        return cast(ast.Call, super().visit_call(node))


def validate_prompt_jev_access(team: "Team") -> None:
    if settings.CLICKHOUSE_USE_HTTP or team.pk in settings.CLICKHOUSE_USE_HTTP_PER_TEAM:
        raise QueryError("jev requires the native ClickHouse connection. Ask your administrator to configure it.")
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
        raise QueryError("jev is not enabled for this project. Contact support to request access.")
    if _is_over_ai_credit_budget(team):
        raise QueryError(OUT_OF_AI_CREDITS_MESSAGE)


def _is_over_ai_credit_budget(team: "Team") -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the HogQL import path
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(team.api_token)
    except Exception:
        # The quota cache reads Redis. An outage must not stop a team that has credits, and a team
        # that is really out of them still gets the same message from the gateway's 402.
        logger.warning("prompt_jev_ai_credit_lookup_failed", team_id=team.pk, exc_info=True)
        return False
