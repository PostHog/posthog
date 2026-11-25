import json
from collections.abc import Iterator, Mapping
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction

import pydantic

from posthog.schema import HogQLVariable

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.flag_evaluations import FlagEvaluationsTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import EmbeddedClickHouseQuery, HogQLQueryExecutor
from posthog.hogql.team_first_prewhere import reads_events_table
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Team, User
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode

MAX_QUERY_BYTES = 100_000
MAX_VARIABLES_BYTES = 100_000
MAX_ACTIVE_REQUESTS_PER_TEAM = 5
ACTIVE_REQUEST_STATUSES = (
    RequestStatus.PENDING,
    RequestStatus.APPROVED,
    RequestStatus.IN_PROGRESS,
    RequestStatus.QUEUED,
)


class DataDeletionSubmissionConflict(Exception):
    pass


class DataDeletionActiveRequestLimit(Exception):
    pass


def validate_payload_size(query: str, variables: dict[str, object]) -> None:
    if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
        raise DjangoValidationError({"query": f"The query must be smaller than {MAX_QUERY_BYTES} bytes."})
    variables_bytes = len(json.dumps(variables, separators=(",", ":")).encode("utf-8"))
    if variables_bytes > MAX_VARIABLES_BYTES:
        raise DjangoValidationError(
            {"variables": f"The query variables must be smaller than {MAX_VARIABLES_BYTES} bytes."}
        )


def compile_event_uuid_query(
    *,
    query: str,
    variables: Mapping[str, object],
    team: Team,
    user: User,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
) -> EmbeddedClickHouseQuery:
    try:
        parsed_variables = {key: HogQLVariable.model_validate(value) for key, value in variables.items()}
    except pydantic.ValidationError as error:
        raise DjangoValidationError({"variables": "The query variables are invalid."}) from error

    compiler = HogQLQueryExecutor(
        query=query,
        team=team,
        user=user,
        user_access_control=UserAccessControl(user=user, team=team),
        # A deletion must reach every stored row, including rows past the retention or coverage floor.
        context=HogQLContext(team_id=team.pk, user=user, apply_events_retention_floor=False),
        variables=parsed_variables,
        workload=Workload.OFFLINE,
        ch_user=ch_user,
        limit_context=None,
        pretty=False,
    )
    try:
        selected = compiler.generate_clickhouse_subquery_sql()
    except (ExposedHogQLError, UserAccessControlError) as error:
        raise DjangoValidationError({"query": str(error)}) from error
    prepared_ast = compiler.clickhouse_prepared_ast
    if not isinstance(prepared_ast, (ast.SelectQuery, ast.SelectSetQuery)) or prepared_ast.type is None:
        raise DjangoValidationError({"query": "The HogQL query must return a result set."})
    if len(prepared_ast.type.columns) != 1:
        raise DjangoValidationError({"query": "The HogQL query must select exactly one event UUID column."})

    output_type = next(iter(prepared_ast.type.columns.values())).resolve_constant_type(selected.context)
    if not isinstance(output_type, ast.UUIDType):
        raise DjangoValidationError({"query": "The selected column must contain event UUIDs."})
    if _misses_flag_calls_only_in_flag_evaluations(prepared_ast, prepared_ast.type, selected.context, team):
        raise DjangoValidationError({"query": MISSES_FLAG_CALLS_ERROR})
    return selected


MISSES_FLAG_CALLS_ERROR = (
    "Some of this project's $feature_flag_called events are stored only in posthog.flag_evaluations, so this "
    "query can't select them. To delete them too, add UNION ALL SELECT uuid FROM posthog.flag_evaluations "
    "WHERE … with the same conditions. To delete none of them, add that branch with WHERE false."
)


def _misses_flag_calls_only_in_flag_evaluations(
    prepared_ast: ast.SelectQuery | ast.SelectSetQuery,
    query_type: ast.SelectQueryType | ast.SelectSetQueryType,
    context: HogQLContext,
    team: Team,
) -> bool:
    """Whether the query reads events while events lacks flag calls that flag_evaluations holds, and no branch of
    its output returns the uuid of a flag_evaluations row. The drain deletes a queued uuid from every table. A query
    that selects flag_evaluations uuids therefore reaches those flag calls."""
    if not reads_events_table(prepared_ast):
        return False
    # The stored mode also counts. FLAG_EVALUATIONS_READS_FORCE_EVENTS moves reads back to events. Events still lacks
    # the flag calls that ingestion wrote before the organization kept its events writes.
    if not (
        context.flag_calls_only_in_flag_evaluations()
        or get_organization_flag_evaluations_mode(team.organization_id) == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
    ):
        return False
    if _uses_non_union_set_operator(prepared_ast):
        return True
    sources = _column_sources(query_type, _column_names(query_type)[0], seen=set())
    return not any(isinstance(table, FlagEvaluationsTable) and field == "uuid" for table, field in sources)


class _NonUnionSetOperatorFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found = self.found or any(
            not set_node.set_operator.startswith("UNION") for set_node in node.subsequent_select_queries
        )
        super().visit_select_set_query(node)


def _uses_non_union_set_operator(prepared_ast: ast.AST) -> bool:
    """`SelectSetQueryType` does not record the set operator. `_column_sources` therefore follows INTERSECT and EXCEPT
    branches as if they were UNION branches. An INTERSECT or EXCEPT output can lack the flag_evaluations rows that a
    branch selects. The guard refuses any query that uses one."""
    finder = _NonUnionSetOperatorFinder()
    finder.visit(prepared_ast)
    return finder.found


def _column_names(source: ast.SelectQueryType | ast.SelectSetQueryType) -> list[str]:
    """The output column names of a query in order. A set query takes them from its first branch, because column
    aliases such as `AS q(a, b)` rename the first branch and leave the set query's own `columns` unchanged."""
    if isinstance(source, ast.SelectSetQueryType):
        return _column_names(source.types[0])
    return list(source.columns)


def _column_sources(source: ast.Type, name: str, *, seen: set[tuple[int, str]]) -> Iterator[tuple[Table, str]]:
    """The table fields that the named column of a table or query returns unchanged. A column that an expression
    computes has no source. The caller treats such a column as returning no flag_evaluations uuid."""
    # The resolver shares one type between every reference to a CTE. Without this set, a CTE that each level
    # selects twice makes the walk exponential in the number of levels.
    if (id(source), name) in seen:
        return
    seen.add((id(source), name))
    match source:
        case ast.TableType():
            yield source.table, name
        case ast.TableAliasType():
            yield from _column_sources(source.table_type, name, seen=seen)
        case ast.ColumnAliasedTableType():
            yield from _column_sources(source.table_type, source.alias_to_original.get(name, name), seen=seen)
        case ast.SelectQueryAliasType() | ast.CTETableType() | ast.SelectViewType():
            yield from _column_sources(source.select_query_type, name, seen=seen)
        case ast.CTETableAliasType():
            yield from _column_sources(source.cte_table_type, name, seen=seen)
        case ast.SelectQueryType():
            column = source.columns.get(name)
            while isinstance(column, ast.FieldAliasType):
                column = column.type
            if isinstance(column, ast.FieldType):
                yield from _column_sources(column.table_type, column.name, seen=seen)
        case ast.SelectSetQueryType():
            # A set query matches its branches' columns by position, not by name.
            names = _column_names(source)
            if name not in names:
                return
            position = names.index(name)
            for branch in source.types:
                branch_names = _column_names(branch)
                if position < len(branch_names):
                    yield from _column_sources(branch, branch_names[position], seen=seen)


def preview_event_deletion(*, query: str, variables: dict[str, object], team: Team, user: User) -> int:
    validate_payload_size(query, variables)
    selected = compile_event_uuid_query(query=query, variables=variables, team=team, user=user)
    count_sql = f"SELECT count() FROM ({selected.sql}) AS selected"  # nosemgrep: clickhouse-injection-taint
    result = sync_execute(
        count_sql,
        selected.context.values,
        workload=Workload.OFFLINE,
        team_id=team.id,
        readonly=True,
        settings=selected.settings,
        external_tables=list(selected.context.external_tables.values()) or None,
    )
    return int(result[0][0]) if result else 0


def create_event_deletion_request(
    *,
    query: str,
    variables: dict[str, object],
    submission_id: UUID,
    team: Team,
    user: User,
) -> tuple[DataDeletionRequest, bool]:
    validate_payload_size(query, variables)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"data-deletion:{team.id}"])

        existing = DataDeletionRequest.objects.filter(team_id=team.id, submission_id=submission_id).first()
        if existing is not None:
            if (
                existing.request_type != RequestType.HOGQL_EVENT_REMOVAL
                or existing.hogql_query != query
                or existing.hogql_variables != variables
                or existing.created_by_id != user.id
            ):
                raise DataDeletionSubmissionConflict
            return existing, False

        active_count = DataDeletionRequest.objects.filter(
            team_id=team.id,
            request_type=RequestType.HOGQL_EVENT_REMOVAL,
            status__in=ACTIVE_REQUEST_STATUSES,
        ).count()
        if active_count >= MAX_ACTIVE_REQUESTS_PER_TEAM:
            raise DataDeletionActiveRequestLimit

        compile_event_uuid_query(query=query, variables=variables, team=team, user=user)

        deletion_request = DataDeletionRequest(
            team_id=team.id,
            request_type=RequestType.HOGQL_EVENT_REMOVAL,
            hogql_query=query,
            hogql_variables=variables,
            submission_id=submission_id,
            created_by=user,
            created_by_staff=user.is_staff,
            criteria_updated_by=user,
            status=RequestStatus.PENDING,
            requires_approval=True,
            execution_mode=ExecutionMode.DEFERRED,
        )
        deletion_request.full_clean()
        deletion_request.save()
        return deletion_request, True
