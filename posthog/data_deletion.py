import json
from collections.abc import Mapping
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction

import pydantic

from posthog.schema import HogQLVariable

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import EmbeddedClickHouseQuery, HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Team, User
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError

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
    return selected


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
