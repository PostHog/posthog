from typing import Literal, Optional, Union, cast

from django.conf import settings

import structlog
from pydantic import BaseModel

from posthog.schema import (
    HogLanguage,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLNotice,
    HogQLQuery,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
)

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR, get_direct_connection_source
from posthog.hogql.direct_sql import get_adapter
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.index_eligibility import build_index_eligibility_report
from posthog.hogql.metadata_heuristics import run_metadata_heuristics
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.observability import (
    INDEX_ELIGIBILITY_DURATION_SECONDS,
    INDEX_ELIGIBILITY_TOTAL,
    INDEX_ELIGIBILITY_VERDICT_TOTAL,
)
from posthog.hogql.parser import parse_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.taxonomy_validation import validate_taxonomy_references
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
    user: Optional[User] = None,
    hogql_ast: Optional[Union[ast.SelectQuery, ast.SelectSetQuery]] = None,
    prepared_ast: Optional[ast.AST] = None,  # precached
    printed_sql: Optional[str] = None,  # precached
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        query=query.query,
        errors=[],
        warnings=[],
        notices=[],
        table_names=[],
    )

    query_modifiers = create_default_modifiers_for_team(team, query.modifiers)
    source = get_direct_connection_source(team, query.connectionId, user=user)
    if query.connectionId and source is None:
        response.isValid = False
        response.errors = [HogQLNotice(message=INVALID_CONNECTION_ID_ERROR)]
        return response

    database = None
    if source:
        database = Database.create_for(
            team=team,
            user=user,
            modifiers=query_modifiers,
            connection_id=str(source.id),
        )

    heuristic_warnings: list[HogQLNotice] = []
    context: Optional[HogQLContext] = None

    try:
        context = HogQLContext(
            team_id=team.pk,
            user=user,
            database=database,
            modifiers=query_modifiers,
            enable_select_queries=True,
            # A resolved direct-connection source prints with its engine dialect (below), so the
            # context must be marked direct — otherwise the ClickHouse printer's direct-table guard
            # fires and metadata/autocomplete reports a false "can only be queried through its direct
            # connection" error for a query that actually runs fine.
            is_direct_query=source is not None,
            debug=query.debug or False,
            globals=query.globals,
        )
        if query.language == HogLanguage.HOG:
            program = parse_program(query.query)
            create_bytecode(program, supported_functions={"fetch", "postHogCapture"}, args=[], context=context)
        elif query.language == HogLanguage.HOG_TEMPLATE:
            string = parse_string_template(query.query)
            create_bytecode(string, supported_functions={"fetch", "postHogCapture"}, args=[], context=context)
        elif query.language == HogLanguage.HOG_QL_EXPR:
            node = parse_expr(query.query)
            if query.sourceQuery is not None:
                source_query = get_query_runner(query=query.sourceQuery, team=team).to_query()
                process_expr_on_table(node, context=context, source_query=source_query)
            else:
                process_expr_on_table(node, context=context)
        elif query.language == HogLanguage.HOG_QL:
            if not hogql_ast:
                hogql_ast = parse_select(query.query)
                finder = find_placeholders(hogql_ast)
                if finder.has_filters:
                    hogql_ast = replace_filters(hogql_ast, query.filters, team, database=database)
                if query.variables or finder.placeholder_fields or finder.placeholder_expressions:
                    hogql_ast = replace_variables(
                        hogql_ast, list(query.variables.values()) if query.variables else [], team
                    )
                    hogql_ast = cast(ast.SelectQuery, replace_placeholders(hogql_ast, query.globals))

            heuristic_warnings.extend(run_metadata_heuristics(hogql_ast))
            hogql_table_names = get_table_names(hogql_ast)
            heuristic_warnings.extend(validate_taxonomy_references(hogql_ast, team, hogql_table_names))
            response.table_names = hogql_table_names

            if not printed_sql or not prepared_ast:
                direct_adapter = get_adapter(source.direct_engine) if source else None
                direct_dialect: HogQLDialect = (
                    direct_adapter.dialect if direct_adapter and direct_adapter.dialect else "postgres"
                )
                printed_sql, prepared_ast = prepare_and_print_ast(
                    clone_expr(hogql_ast),
                    context=context,
                    dialect=direct_dialect if source else "clickhouse",
                )

            if prepared_ast:
                response.ch_table_names = get_table_names(prepared_ast)

            if source is None and query.indexUsage and _index_usage_enabled(team):
                _attach_index_usage(response, hogql_ast, context)
        else:
            raise ValueError(f"Unsupported language: {query.language}")
    except Exception as e:
        response.isValid = False
        if isinstance(e, ExposedHogQLError):
            error = str(e)
            # cpp-json (ANTLR) and rust-py word EOF differently; collapse both into a single human-readable string.
            if "mismatched input '<EOF>' expecting" in error or "unexpected token in expression: Eof" in error:
                error = "Unexpected end of query"
            start, end = e.start, e.end
            if start is not None and end is not None and end < start:
                start, end = end, start
            # A notice without a span marks the whole query, so a fix carried alongside one would
            # replace everything the user typed instead of the token the suggestion stands in for.
            fix = e.fix if start is not None and end is not None else None
            response.errors.append(HogQLNotice(message=error, start=start, end=end, fix=fix))
        elif (
            settings.DEBUG
        ):  # We don't want to accidentally expose too much data via errors, so expose only when debug is enabled
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}: {str(e)}"))
        else:
            response.errors.append(HogQLNotice(message=f"Unexpected {e.__class__.__name__}"))
    finally:
        if context is not None:
            response.warnings = [*context.warnings, *heuristic_warnings]
            response.notices = context.notices
            if response.errors:
                response.errors = [*context.errors, *response.errors]
            else:
                response.errors = context.errors
            response.isValid = len(response.errors) == 0

    # We add a magic "F'" start prefix to get Antlr into the right parsing mode, subtract it now
    if query.language == HogLanguage.HOG_TEMPLATE:
        for err in response.errors:
            if err.start is not None and err.end is not None and err.start > 0:
                err.start -= 2
                err.end -= 2

    return response


def _index_usage_enabled(team: Team) -> bool:
    """Index eligibility is still being calibrated against real query plans, so it stays off by default.

    The verdicts are reasoned from ClickHouse semantics rather than measured, and a wrong verdict is
    indistinguishable from a right one to whoever reads it. Rolling out behind a flag keeps that
    exposure where the analysis can be checked against what queries actually do.
    """
    return feature_enabled_or_false(
        "hogql-index-eligibility",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
    )


def _attach_index_usage(
    response: HogQLMetadataResponse,
    hogql_ast: Union[ast.SelectQuery, ast.SelectSetQuery],
    context: HogQLContext,
) -> None:
    """Report which property filters will prune data, and warn about the ones a fix would unblock.

    Every predicate reaches the response; only the ones a query edit can unblock become warnings.
    Reading a property out of the JSON blob is the normal case for most teams, and how a property is
    stored is not something the editor can change, so marking either would bury the predicates where
    a type mismatch is wasting an index that already exists.
    """
    with INDEX_ELIGIBILITY_DURATION_SECONDS.time():
        try:
            report = build_index_eligibility_report(hogql_ast, context)
        except Exception:
            # Index eligibility is advisory. A query that compiles must not be reported as invalid
            # because the analysis over it failed. The counter is the only user-visible trace of that:
            # the response just comes back without a report.
            INDEX_ELIGIBILITY_TOTAL.labels(result="failed").inc()
            logger.exception("hogql_index_eligibility_failed", team_id=context.team_id)
            return

    INDEX_ELIGIBILITY_TOTAL.labels(result="ok").inc()
    for predicate in report.predicates:
        INDEX_ELIGIBILITY_VERDICT_TOTAL.labels(
            verdict=predicate.verdict.value, source_kind=predicate.source_kind.value
        ).inc()

    response.isUsingIndices = report.usage
    response.index_usage = [
        PredicateIndexUsage(
            property_name=predicate.property_name,
            scope=PredicateScope(predicate.scope.value),
            operator=predicate.operator.value,
            source_label=predicate.source_label,
            column_name=predicate.column_name,
            semantic_type=predicate.semantic_type,
            physical_type=predicate.physical_type,
            usable_indexes=[index.value for index in predicate.usable_indexes],
            verdict=PredicateIndexVerdict(predicate.verdict.value),
            message=predicate.message,
            fix=predicate.fix,
            start=predicate.start,
            end=predicate.end,
        )
        for predicate in report.predicates
    ]

    for predicate in report.predicates:
        if predicate.editor_actionable:
            # `HogQLNotice.fix` is literal replacement text for the marked range (see
            # taxonomy_validation), so the prose advice must not go here. The `ai_prompt:` form is
            # the editor's other contract: it becomes a "Fix with AI" action instead of an edit.
            context.add_warning(
                message=predicate.message,
                start=predicate.start,
                end=predicate.end,
                fix=f"ai_prompt:{predicate.ai_fix_prompt}" if predicate.ai_fix_prompt else None,
            )


def enrich_hogql_validation_error(
    query: BaseModel | None,
    team: Team,
    user: Optional[User],
    original_detail: str,
) -> tuple[str, dict | None]:
    """When a HogQLQuery fails, run it through metadata resolution to collect
    structured error positions, table references, and any fix hints. Returns a
    (possibly enriched) detail string and a dict suitable for exceptions_hog's
    ``extra`` attribute — or ``(original_detail, None)`` when enrichment isn't
    applicable or fails.
    """
    if not isinstance(query, HogQLQuery) or not query.query:
        return original_detail, None

    try:
        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query=query.query,
                modifiers=query.modifiers,
                filters=query.filters,
                connectionId=query.connectionId,
            ),
            team=team,
            user=user,
        )
    except Exception:
        return original_detail, None

    lines: list[str] = [original_detail]

    for notice in [*metadata.errors, *metadata.warnings, *metadata.notices]:
        if notice.fix and notice.fix not in lines:
            lines.append(f"Hint: {notice.fix}")

    if metadata.table_names:
        lines.append(f"Tables referenced: {', '.join(metadata.table_names)}")

    extra = {"hogql_metadata": metadata.model_dump(mode="json", exclude_none=True)}
    return "\n".join(lines), extra


def process_expr_on_table(
    node: ast.Expr,
    context: HogQLContext,
    source_query: Optional[ast.SelectQuery | ast.SelectSetQuery] = None,
):
    try:
        if source_query is not None:
            select_query = cast(ast.SelectQuery, clone_expr(source_query, clear_locations=True))
            select_query.select.append(node)
        else:
            select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))

        # Nothing to return, we just make sure it doesn't throw
        dialect: Literal["clickhouse", "postgres", "mysql"] = "clickhouse"
        if getattr(context.database, "_connection_id", None):
            connection_metadata = getattr(context.database, "_direct_connection_metadata", None)
            engine = connection_metadata.get("engine") if isinstance(connection_metadata, dict) else None
            dialect = "mysql" if engine == "mysql" else "postgres"
        prepare_and_print_ast(select_query, context, dialect)
    except (NotImplementedError, SyntaxError):
        raise


def get_table_names(select_query: AST) -> list[str]:
    # Don't need types, we're only interested in the table names as passed in
    collector = TableCollector()
    collector.visit(select_query)
    return list(collector.table_names - collector.ctes)


class TableCollector(TraversingVisitor):
    def __init__(self):
        self.table_names = set()
        self.ctes = set()

    def visit_cte(self, node: ast.CTE):
        self.ctes.add(node.name)
        super().visit(node.expr)

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field):
            self.table_names.add(".".join([str(x) for x in node.table.chain]))
        else:
            self.visit(node.table)

        self.visit(node.next_join)
