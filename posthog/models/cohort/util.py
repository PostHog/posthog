import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional, Union, cast

from django.conf import settings
from django.utils import timezone

import structlog
import posthoganalytics
from dateutil import parser
from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.resolver_utils import extract_select_queries

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries, tags_context
from posthog.constants import PropertyOperatorType
from posthog.models import Action, Filter, Team
from posthog.models.action.util import format_action_filter
from posthog.models.cohort.calculation_history import CohortCalculationHistory
from posthog.models.cohort.cohort import Cohort, CohortOrEmpty, CohortPeople
from posthog.models.cohort.dependencies import get_cohort_dependents
from posthog.models.cohort.sql import (
    CALCULATE_COHORT_PEOPLE_SQL,
    GET_COHORT_SIZE_SQL,
    GET_COHORTS_BY_PERSON_UUID,
    GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID,
    GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID,
    RECALCULATE_COHORT_BY_ID,
)
from posthog.models.person.sql import (
    DELETE_PERSON_FROM_STATIC_COHORT,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.models.property import Property, PropertyGroup
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.util import PersonPropertiesMode

# temporary marker to denote when cohortpeople table started being populated
TEMP_PRECALCULATED_MARKER = parser.parse("2021-06-07T15:00:00+00:00")
TARGET_CHUNK_SIZE = 5_000_000

logger = structlog.get_logger(__name__)


def run_cohort_query(
    fn, *args, cohort_id: int, history: CohortCalculationHistory | None = None, query: str | None = None, **kwargs
):
    """
    Run a cohort calculation function with delayed query performance tracking.

    Args:
        fn: Function to execute
        cohort_id: ID of the cohort being calculated
        history_id: Optional UUID string of CohortCalculationHistory to update with delayed stats
        query: Optional SQL query string to be logged with stats
        *args, **kwargs: Arguments passed to fn

    Returns:
        tuple: (result, end_time) where end_time is when the query finished
    """
    tracking_uuid = uuid.uuid4().hex[:8]
    cohort_tag = f"cohort_calc:{tracking_uuid}"

    # Store the start time before running the query
    start_time = timezone.now()

    # Tag the query for tracking
    tag_queries(kind="cohort_calculation", id=cohort_tag)

    try:
        result = fn(*args, **kwargs)
        end_time = timezone.now()  # Capture when query actually finished

        return result, end_time

    finally:
        # Schedule delayed task to collect stats after query_log_archive is synced
        # Only if we have a history record to update
        if history and query:
            from posthog.tasks.calculate_cohort import collect_cohort_query_stats

            collect_cohort_query_stats.apply_async(
                args=[cohort_tag, cohort_id, start_time.isoformat(), history.id, query],
                countdown=60,
            )
        # Reset query tags to avoid affecting other queries
        from posthog.clickhouse.query_tagging import reset_query_tags

        reset_query_tags()


def get_clickhouse_query_stats(tag_matcher: str, cohort_id: int, start_time: datetime, team_id: int) -> Optional[dict]:
    """
    Retrieve query statistics from ClickHouse query_log_archive using query tags.
    Similar to approach in ee/benchmarks/helpers.py but adapted for cohort calculations.
    """
    if not tag_matcher:
        return None

    try:
        result = sync_execute(
            """
            SELECT
                query_id,
                query_duration_ms,
                read_rows,
                read_bytes,
                written_rows,
                memory_usage,
                exception
            FROM query_log_archive
            WHERE
                lc_cohort_id = %(cohort_id)s
                AND team_id = %(team_id)s
                AND query LIKE %(matcher)s
                AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
                AND event_date >= %(start_date)s
                AND event_time >= %(start_time)s
            ORDER BY event_time DESC
            """,
            {
                "cohort_id": cohort_id,
                "team_id": team_id,
                "matcher": f"%{tag_matcher}%",
                "start_date": start_time.date(),
                "start_time": start_time,
            },
            settings={"max_execution_time": 10},
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.COHORTS,
        )

        if result and len(result) > 0:
            # Helper function to safely get column values
            def get_column(rows, col_index):
                return [row[col_index] for row in rows if len(row) > col_index and row[col_index] is not None]

            # Get the most recent query (first row after ORDER BY event_time DESC)
            first_row = result[0]

            return {
                "query_id": first_row[0] if len(first_row) > 0 else None,
                "query_count": len(result),
                "query_duration_ms": int(sum(get_column(result, 1))),
                "read_rows": sum(get_column(result, 2)),
                "read_bytes": sum(get_column(result, 3)),
                "written_rows": sum(get_column(result, 4)),
                "memory_mb": int(sum(get_column(result, 5)) / 1024 / 1024) if get_column(result, 5) else 0,
                "exception": first_row[6] if len(first_row) > 6 else None,
            }

    except Exception as e:
        logger.exception("Failed to retrieve ClickHouse query stats", tag_matcher=tag_matcher, error=str(e))

    return None


def format_person_query(cohort: Cohort, index: int, hogql_context: HogQLContext) -> tuple[str, dict[str, Any]]:
    if cohort.is_static:
        return format_static_cohort_query(cohort, index, prepend="")

    if not cohort.properties.values:
        # No person can match an empty cohort
        return "SELECT generateUUIDv4() as id WHERE 0 = 19", {}

    from posthog.queries.cohort_query import CohortQuery

    query_builder = CohortQuery(
        Filter(
            data={"properties": cohort.properties},
            team=cohort.team,
            hogql_context=hogql_context,
        ),
        cohort.team,
        cohort_pk=cohort.pk,
        persons_on_events_mode=cohort.team.person_on_events_mode,
    )

    query, params = query_builder.get_query()

    return query, params


def print_cohort_hogql_query(cohort: Cohort, hogql_context: HogQLContext, *, team: Team) -> str:
    from posthog.hogql_queries.query_runner import get_query_runner

    if not cohort.query:
        raise ValueError("Cohort has no query")

    query = get_query_runner(
        cast(dict, cohort.query), team=team, limit_context=LimitContext.COHORT_CALCULATION
    ).to_query()

    for select_query in extract_select_queries(query):
        columns: dict[str, ast.Expr] = {}
        for expr in select_query.select:
            if isinstance(expr, ast.Alias):
                columns[expr.alias] = expr.expr
            elif isinstance(expr, ast.Field):
                columns[str(expr.chain[-1])] = expr
        column: ast.Expr | None = columns.get("person_id") or columns.get("actor_id") or columns.get("id")
        if isinstance(column, ast.Alias):
            select_query.select = [ast.Alias(expr=column.expr, alias="actor_id")]
        elif isinstance(column, ast.Field):
            select_query.select = [ast.Alias(expr=column, alias="actor_id")]
        else:
            # Support the most common use cases
            table = select_query.select_from.table if select_query.select_from else None
            if isinstance(table, ast.Field) and table.chain[-1] == "events":
                select_query.select = [ast.Alias(expr=ast.Field(chain=["person", "id"]), alias="actor_id")]
            elif isinstance(table, ast.Field) and table.chain[-1] == "persons":
                select_query.select = [ast.Alias(expr=ast.Field(chain=["id"]), alias="actor_id")]
            else:
                raise ValueError("Could not find a person_id, actor_id, or id column in the query")

    hogql_context.enable_select_queries = True
    hogql_context.limit_top_select = False
    create_default_modifiers_for_team(team, hogql_context.modifiers)

    # Apply HogQL global settings to ensure consistency with regular queries
    settings = HogQLGlobalSettings()
    return prepare_and_print_ast(query, context=hogql_context, dialect="clickhouse", settings=settings)[0]


def format_static_cohort_query(cohort: Cohort, index: int, prepend: str) -> tuple[str, dict[str, Any]]:
    cohort_id = cohort.pk
    return (
        f"SELECT person_id as id FROM {PERSON_STATIC_COHORT_TABLE} WHERE cohort_id = %({prepend}_cohort_id_{index})s AND team_id = %(team_id)s",
        {f"{prepend}_cohort_id_{index}": cohort_id},
    )


def format_precalculated_cohort_query(cohort: Cohort, index: int, prepend: str = "") -> tuple[str, dict[str, Any]]:
    filter_query = GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID.format(index=index, prepend=prepend)
    return (
        filter_query,
        {
            f"{prepend}_cohort_id_{index}": cohort.pk,
            f"{prepend}_version_{index}": cohort.version,
        },
    )


def get_count_operator(count_operator: Optional[str]) -> str:
    if count_operator == "gte":
        return ">="
    elif count_operator == "lte":
        return "<="
    elif count_operator == "gt":
        return ">"
    elif count_operator == "lt":
        return "<"
    elif count_operator == "eq" or count_operator == "exact" or count_operator is None:
        return "="
    else:
        raise ValidationError("count_operator must be gte, lte, eq, or None")


def get_count_operator_ast(count_operator: Optional[str]) -> ast.CompareOperationOp:
    if count_operator == "gte":
        return ast.CompareOperationOp.GtEq
    elif count_operator == "lte":
        return ast.CompareOperationOp.LtEq
    elif count_operator == "gt":
        return ast.CompareOperationOp.Gt
    elif count_operator == "lt":
        return ast.CompareOperationOp.Lt
    elif count_operator == "eq" or count_operator == "exact" or count_operator is None:
        return ast.CompareOperationOp.Eq
    else:
        raise ValidationError("count_operator must be gte, lte, eq, or None")


def get_entity_query(
    event_id: Optional[str],
    action_id: Optional[int],
    team_id: int,
    group_idx: Union[int, str],
    hogql_context: HogQLContext,
    person_properties_mode: Optional[PersonPropertiesMode] = None,
) -> tuple[str, dict[str, str]]:
    if event_id:
        return f"event = %({f'event_{group_idx}'})s", {f"event_{group_idx}": event_id}
    elif action_id:
        action = Action.objects.get(pk=action_id)
        action_filter_query, action_params = format_action_filter(
            team_id=team_id,
            action=action,
            prepend="_{}_action".format(group_idx),
            hogql_context=hogql_context,
            person_properties_mode=(
                person_properties_mode if person_properties_mode else PersonPropertiesMode.USING_SUBQUERY
            ),
        )
        return action_filter_query, action_params
    else:
        raise ValidationError("Cohort query requires action_id or event_id")


def get_date_query(
    days: Optional[str], start_time: Optional[str], end_time: Optional[str]
) -> tuple[str, dict[str, str]]:
    date_query: str = ""
    date_params: dict[str, str] = {}
    if days:
        date_query, date_params = parse_entity_timestamps_in_days(int(days))
    elif start_time or end_time:
        date_query, date_params = parse_cohort_timestamps(start_time, end_time)

    return date_query, date_params


def parse_entity_timestamps_in_days(days: int) -> tuple[str, dict[str, str]]:
    curr_time = timezone.now()
    start_time = curr_time - timedelta(days=days)

    return (
        "AND timestamp >= %(date_from)s AND timestamp <= %(date_to)s",
        {
            "date_from": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "date_to": curr_time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def parse_cohort_timestamps(start_time: Optional[str], end_time: Optional[str]) -> tuple[str, dict[str, str]]:
    clause = "AND "
    params: dict[str, str] = {}

    if start_time:
        clause += "timestamp >= %(date_from)s"

        params = {"date_from": datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")}
    if end_time:
        clause += "timestamp <= %(date_to)s"
        params = {
            **params,
            "date_to": datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S"),
        }

    return clause, params


def is_precalculated_query(cohort: Cohort) -> bool:
    if (
        cohort.last_calculation
        and cohort.last_calculation > TEMP_PRECALCULATED_MARKER
        and settings.USE_PRECALCULATED_CH_COHORT_PEOPLE
        and not cohort.is_static  # static cohorts are handled within the regular cohort filter query path
    ):
        return True
    else:
        return False


def format_filter_query(
    cohort: Cohort,
    index: int,
    hogql_context: HogQLContext,
    id_column: str = "distinct_id",
    custom_match_field="person_id",
) -> tuple[str, dict[str, Any]]:
    person_query, params = format_cohort_subquery(cohort, index, hogql_context, custom_match_field=custom_match_field)

    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query,
        id_column=id_column,
        GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
    )
    return person_id_query, params


def format_cohort_subquery(
    cohort: Cohort, index: int, hogql_context: HogQLContext, custom_match_field="person_id"
) -> tuple[str, dict[str, Any]]:
    is_precalculated = is_precalculated_query(cohort)
    if is_precalculated:
        query, params = format_precalculated_cohort_query(cohort, index)
    else:
        query, params = format_person_query(cohort, index, hogql_context)

    person_query = f"{custom_match_field} IN ({query})"
    return person_query, params


def insert_static_cohort(person_uuids: list[Optional[uuid.UUID]], cohort_id: int, *, team_id: int):
    tag_queries(cohort_id=cohort_id, team_id=team_id, name="insert_static_cohort", feature=Feature.COHORT)
    persons = [
        {
            "id": str(uuid.uuid4()),
            "person_id": str(person_uuid),
            "cohort_id": cohort_id,
            "team_id": team_id,
            "_timestamp": datetime.now(),
        }
        for person_uuid in person_uuids
    ]
    sync_execute(INSERT_PERSON_STATIC_COHORT, persons)


def remove_person_from_static_cohort(person_uuid: uuid.UUID, cohort_id: int, *, team_id: int):
    """Remove a person from a static cohort in ClickHouse.

    Uses DELETE FROM with mutations_sync=0 to avoid replica synchronization issues in production.
    This is an exception to PostHog's usual pattern due to the table lacking an is_deleted and version columns.
    """
    tag_queries(cohort_id=cohort_id, team_id=team_id, name="remove_person_from_static_cohort", feature=Feature.COHORT)
    sync_execute(
        DELETE_PERSON_FROM_STATIC_COHORT,
        {
            "person_id": str(person_uuid),
            "cohort_id": cohort_id,
            "team_id": team_id,
        },
        settings={"mutations_sync": "0"},
    )


def get_static_cohort_size(*, cohort_id: int, team_id: int) -> int:
    count = CohortPeople.objects.filter(cohort_id=cohort_id, person__team_id=team_id).count()

    return count


def recalculate_cohortpeople(
    cohort: Cohort, pending_version: int, *, initiating_user_id: Optional[int]
) -> Optional[int]:
    """
    Recalculate cohort people for all environments of the project.
    NOTE: Currently, this only returns the count for the team where the cohort was created. Instead, it should return for all teams.
    """
    relevant_teams = Team.objects.order_by("id").filter(project_id=cohort.team.project_id)
    count_by_team_id: dict[int, int] = {}
    tag_queries(cohort_id=cohort.id)
    if initiating_user_id:
        tag_queries(user_id=initiating_user_id)
    for team in relevant_teams:
        tag_queries(team_id=team.id)
        _recalculate_cohortpeople_for_team_hogql(cohort, pending_version, team)
        count: Optional[int]
        if cohort.is_static:
            count = get_static_cohort_size(cohort_id=cohort.id, team_id=team.id)
        else:
            count = get_cohort_size(cohort, override_version=pending_version, team_id=team.id)
        count_by_team_id[team.id] = count if count is not None else 0

    return count_by_team_id[cohort.team_id]


def _recalculate_cohortpeople_for_team_hogql(cohort: Cohort, pending_version: int, team: Team) -> int:
    tag_queries(name="recalculate_cohortpeople_for_team_hogql")

    history = CohortCalculationHistory.objects.create(
        team=team, cohort=cohort, filters=cohort.properties.to_dict() if cohort.properties.values else {}
    )

    try:
        estimated_size = cohort.count if cohort.count else 0
        chunk_size = _get_cohort_chunking_config(cohort, team.uuid, team.organization.id, estimated_size)
        if chunk_size is not None:
            total_chunks = max(math.ceil(estimated_size / chunk_size), 1)
            result = _recalculate_cohortpeople_chunked(cohort, pending_version, team, total_chunks, history)
        else:
            result = _recalculate_cohortpeople_standard(cohort, pending_version, team, history)

        return result

    except Exception as e:
        history.finished_at = timezone.now()
        history.error = str(e)
        history.save(update_fields=["finished_at", "error"])
        raise


def _recalculate_cohortpeople_standard(
    cohort: Cohort, pending_version: int, team: Team, history: CohortCalculationHistory
) -> int:
    """Standard non-chunked cohort calculation with metrics tracking"""
    cohort_params: dict[str, Any]
    if cohort.is_static:
        cohort_query, cohort_params = format_static_cohort_query(cohort, 0, prepend="")
    elif not cohort.properties.values:
        history.finished_at = timezone.now()
        history.count = 0
        history.error = "Cohort has no properties defined"
        history.save(update_fields=["finished_at", "count", "error"])
        return 0
    else:
        from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery

        cohort_query, hogql_context = (
            HogQLCohortQuery(cohort=cohort, team=team).get_query_executor().generate_clickhouse_sql()
        )
        cohort_params = hogql_context.values

        # Hacky: Clickhouse doesn't like there being a top level "SETTINGS" clause in a SelectSet statement when that SelectSet
        # statement is used in a subquery. We remove it here.
        cohort_query = cohort_query[: cohort_query.rfind("SETTINGS")]

    recalculate_cohortpeople_sql = RECALCULATE_COHORT_BY_ID.format(cohort_filter=cohort_query)

    def execute_query():
        tag_queries(
            kind="cohort_calculation",
            query_type="CohortsQueryHogQL",
            feature=Feature.COHORT,
            cohort_id=cohort.pk,
            team_id=team.id,
        )
        hogql_global_settings = HogQLGlobalSettings()

        return sync_execute(
            recalculate_cohortpeople_sql,
            {
                **cohort_params,
                "cohort_id": cohort.pk,
                "team_id": team.id,
                "new_version": pending_version,
            },
            settings={
                "max_execution_time": 600,
                "send_timeout": 600,
                "receive_timeout": 600,
                "optimize_on_insert": 0,
                "max_ast_elements": hogql_global_settings.max_ast_elements,
                "max_expanded_ast_elements": hogql_global_settings.max_expanded_ast_elements,
                "max_bytes_ratio_before_external_group_by": 0.5,
                "max_bytes_ratio_before_external_sort": 0.5,
            },
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.COHORTS,
        )

    result, query_end_time = run_cohort_query(
        execute_query,
        cohort_id=cohort.pk,
        history=history,
        query=recalculate_cohortpeople_sql,
    )

    if history:
        try:
            history.finished_at = query_end_time
            if isinstance(result, list) and len(result) == 0:
                history.count = 0
            else:
                history.count = result

            history.save(update_fields=["finished_at", "count"])

        except Exception as e:
            history.finished_at = timezone.now()
            history.error = str(e)
            history.save(update_fields=["finished_at", "error"])
            raise

    return result


def _recalculate_cohortpeople_chunked(
    cohort: Cohort, pending_version: int, team: Team, total_chunks: int, history: CohortCalculationHistory
) -> int:
    """Chunked cohort calculation to prevent OOMs with metrics tracking"""
    total_inserted = 0

    for chunk_index in range(total_chunks):
        chunk_cohort_params: dict[str, Any]
        from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery

        chunk_cohort_query, hogql_context = (
            HogQLCohortQuery(cohort=cohort, team=team, chunk_index=chunk_index, total_chunks=total_chunks)
            .get_query_executor()
            .generate_clickhouse_sql()
        )
        chunk_cohort_params = hogql_context.values

        # Remove SETTINGS clause for subquery compatibility
        chunk_cohort_query = chunk_cohort_query[: chunk_cohort_query.rfind("SETTINGS")]

        chunk_recalculate_cohortpeople_sql = RECALCULATE_COHORT_BY_ID.format(cohort_filter=chunk_cohort_query)

        def execute_chunk_query(sql=chunk_recalculate_cohortpeople_sql, params=chunk_cohort_params):
            tag_queries(
                kind="cohort_calculation_chunk",
                query_type="CohortsQueryHogQL",
                feature=Feature.COHORT,
                cohort_id=cohort.pk,
                team_id=team.id,
            )
            hogql_global_settings = HogQLGlobalSettings()

            return sync_execute(
                sql,
                {
                    **params,
                    "cohort_id": cohort.pk,
                    "team_id": team.id,
                    "new_version": pending_version,
                },
                settings={
                    "max_execution_time": 600,
                    "send_timeout": 600,
                    "receive_timeout": 600,
                    "optimize_on_insert": 0,
                    "max_ast_elements": hogql_global_settings.max_ast_elements,
                    "max_expanded_ast_elements": hogql_global_settings.max_expanded_ast_elements,
                    "max_bytes_ratio_before_external_group_by": 0.5,
                    "max_bytes_ratio_before_external_sort": 0.5,
                },
                workload=Workload.OFFLINE,
                ch_user=ClickHouseUser.COHORTS,
            )

        chunk_result, _ = run_cohort_query(
            execute_chunk_query, cohort_id=cohort.pk, history=history, query=chunk_recalculate_cohortpeople_sql
        )

        chunk_inserted = chunk_result or 0
        total_inserted += chunk_inserted

    if history:
        try:
            history.finished_at = timezone.now()
            history.count = total_inserted
            history.save(update_fields=["finished_at", "count"])

        except Exception as e:
            history.finished_at = timezone.now()
            history.error = str(e)
            history.save(update_fields=["finished_at", "error"])
            raise

    return total_inserted


def get_cohort_size(cohort: Cohort, override_version: Optional[int] = None, *, team_id: int) -> Optional[int]:
    tag_queries(name="get_cohort_size", feature=Feature.COHORT)
    count_result = sync_execute(
        GET_COHORT_SIZE_SQL,
        {
            "cohort_id": cohort.pk,
            "version": override_version if override_version is not None else cohort.version,
            "team_id": team_id,
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.COHORTS,
    )

    if count_result and len(count_result) and len(count_result[0]):
        return count_result[0][0]
    else:
        return None


def simplified_cohort_filter_properties(cohort: Cohort, team: Team, is_negated=False) -> PropertyGroup:
    """
    'Simplifies' cohort property filters, removing team-specific context from properties.
    """
    if cohort.is_static:
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[Property(type="static-cohort", key="id", value=cohort.pk, negation=is_negated)],
        )

    # Cohort has been precalculated
    if is_precalculated_query(cohort):
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(
                    type="precalculated-cohort",
                    key="id",
                    value=cohort.pk,
                    negation=is_negated,
                )
            ],
        )

    # Cohort can have multiple match groups.
    # Each group is either
    # 1. "user has done X in time range Y at least N times" or
    # 2. "user has properties XYZ", including belonging to another cohort
    #
    # Users who match _any_ of the groups are considered to match the cohort.

    for property in cohort.properties.flat:
        if property.type == "behavioral":
            # TODO: Support behavioral property type in other insights
            return PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[Property(type="cohort", key="id", value=cohort.pk, negation=is_negated)],
            )

        elif property.type == "cohort":
            # If entire cohort is negated, just return the negated cohort.
            if is_negated:
                return PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="cohort",
                            key="id",
                            value=cohort.pk,
                            negation=is_negated,
                        )
                    ],
                )
            # :TRICKY: We need to ensure we don't have infinite loops in here
            # guaranteed during cohort creation
            return Filter(data={"properties": cohort.properties.to_dict()}, team=team).property_groups

    # We have person properties only
    # TODO: Handle negating a complete property group
    if is_negated:
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[Property(type="cohort", key="id", value=cohort.pk, negation=is_negated)],
        )
    else:
        return cohort.properties


def _get_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> list[int]:
    tag_queries(name="get_cohort_ids_by_person_uuid", feature=Feature.COHORT)
    res = sync_execute(GET_COHORTS_BY_PERSON_UUID, {"person_id": uuid, "team_id": team_id})
    cohort_ids_from_cohortperson = [row[0] for row in res]
    cohorts = Cohort.objects.filter(deleted=False, team_id=team_id, pk__in=cohort_ids_from_cohortperson)
    values_list_result = cohorts.values_list("id", "version")
    id_latest_version_map = dict(values_list_result)
    cohort_ids = []
    for row in res:
        cohort_id_from_cohortperson = row[0]
        version_from_cohortperson = row[1]
        latest_version = id_latest_version_map.get(cohort_id_from_cohortperson)
        if latest_version is None:
            continue
        if latest_version != version_from_cohortperson:
            continue
        cohort_ids.append(cohort_id_from_cohortperson)
    return cohort_ids


def _get_static_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> list[int]:
    tag_queries(name="get_static_cohort_ids_by_person_uuid", feature=Feature.COHORT)
    res = sync_execute(GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID, {"person_id": uuid, "team_id": team_id})
    return [row[0] for row in res]


def get_all_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> list[int]:
    with tags_context(team_id=team_id):
        cohort_ids = _get_cohort_ids_by_person_uuid(uuid, team_id)
        static_cohort_ids = _get_static_cohort_ids_by_person_uuid(uuid, team_id)
    return [*cohort_ids, *static_cohort_ids]


def get_all_cohort_dependencies(
    cohort: Cohort,
    using_database: str = "default",
    seen_cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
) -> list[Cohort]:
    if seen_cohorts_cache is None:
        seen_cohorts_cache = {}

    cohorts = []
    seen_cohort_ids = set()
    seen_cohort_ids.add(cohort.id)

    queue = []
    for prop in cohort.properties.flat:
        if prop.type == "cohort" and not isinstance(prop.value, list):
            try:
                queue.append(int(prop.value))
            except (ValueError, TypeError):
                continue

    while queue:
        cohort_id = queue.pop()
        try:
            if cohort_id in seen_cohorts_cache:
                current_cohort = seen_cohorts_cache[cohort_id]
                if not current_cohort:
                    continue
            else:
                current_cohort = Cohort.objects.db_manager(using_database).get(
                    pk=cohort_id, team__project_id=cohort.team.project_id, deleted=False
                )
                seen_cohorts_cache[cohort_id] = current_cohort
            if current_cohort.id not in seen_cohort_ids:
                cohorts.append(current_cohort)
                seen_cohort_ids.add(current_cohort.id)

                for prop in current_cohort.properties.flat:
                    if prop.type == "cohort" and not isinstance(prop.value, list):
                        try:
                            queue.append(int(prop.value))
                        except (ValueError, TypeError):
                            continue

        except Cohort.DoesNotExist:
            seen_cohorts_cache[cohort_id] = ""
            continue

    return cohorts


def get_all_cohort_dependents(cohort: Cohort, using_database: str = "default") -> list[Cohort]:
    """
    Get all cohorts that reference the given cohort, traversing the full dependent chain.
    For example: if A depends on B, and B depends on C, this returns [A, B] for cohort C.
    This is the reverse traversal of get_dependency_cohorts.
    """
    cohorts: list[int] = []
    seen_cohort_ids: set[int] = {cohort.id}
    queue: list[int] = [cohort.id]

    while queue:
        cohort_id = queue.pop()

        for related_id in get_cohort_dependents(cohort_id):
            if related_id not in seen_cohort_ids:
                queue.append(related_id)
                seen_cohort_ids.add(related_id)

        if cohort_id != cohort.id:
            cohorts.append(cohort_id)

    try:
        dependent_cohorts = Cohort.objects.db_manager(using_database).filter(id__in=cohorts, deleted=False).all()
        return list(dependent_cohorts)
    except Exception as e:
        logger.exception("Failed to fetch cohorts", error=str(e))
    return []


def sort_cohorts_topologically(cohort_ids: set[int], seen_cohorts_cache: dict[int, CohortOrEmpty]) -> list[int]:
    """
    Sorts the given cohorts in an order where cohorts with no dependencies are placed first,
    followed by cohorts that depend on the preceding ones. It ensures that each cohort in the sorted list
    only depends on cohorts that appear earlier in the list.
    """

    if not cohort_ids:
        return []

    dependency_graph: dict[int, list[int]] = {}
    seen = set()

    # build graph (adjacency list)
    def traverse(cohort):
        # add parent
        dependency_graph[cohort.id] = []
        for prop in cohort.properties.flat:
            if prop.type == "cohort" and not isinstance(prop.value, list):
                # add child
                dependency_graph[cohort.id].append(int(prop.value))

                neighbor_cohort = seen_cohorts_cache.get(int(prop.value))
                if not neighbor_cohort:
                    continue

                if cohort.id not in seen:
                    seen.add(cohort.id)
                    traverse(neighbor_cohort)

    for cohort_id in cohort_ids:
        cohort = seen_cohorts_cache.get(int(cohort_id))
        if not cohort:
            continue
        traverse(cohort)

    # post-order DFS (children first, then the parent)
    def dfs(node, seen, sorted_arr):
        neighbors = dependency_graph.get(node, [])
        for neighbor in neighbors:
            if neighbor not in seen:
                dfs(neighbor, seen, sorted_arr)
        if seen_cohorts_cache.get(node):
            sorted_arr.append(int(node))
        seen.add(node)

    sorted_cohort_ids: list[int] = []
    seen = set()
    for cohort_id in cohort_ids:
        if cohort_id not in seen:
            seen.add(cohort_id)
            dfs(cohort_id, seen, sorted_cohort_ids)

    return sorted_cohort_ids


def _get_cohort_chunking_config(
    cohort: Cohort, team_uuid: uuid.UUID, organization_id: int, estimated_size: int
) -> int | None:
    """
    Get chunk size from feature flag, or None if chunking is disabled.

    The chunk size determines how large each chunk should be when processing
    large cohorts. If the flag is disabled or any errors occur, returns None
    to indicate chunking should not be used.

    Args:
        cohort: The cohort being calculated
        team_uuid: UUID of the team
        organization_id: ID of the organization

    Returns:
        Optional[int]: chunk_size if chunking enabled (defaults to TARGET_CHUNK_SIZE),
                       None if chunking is disabled or cohort is static or has zero estimated size
    """
    if cohort.is_static:
        return None

    if estimated_size == 0:
        return None

    try:
        result = posthoganalytics.get_feature_flag_result(
            "cohort-calculation-chunked",
            str(team_uuid),
            groups={"organization": str(organization_id)},
            group_properties={"organization": {"id": str(organization_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

        if result is None or not result.enabled or result.payload is None:
            return None

        chunk_size = result.payload.get("chunk_size")

        if isinstance(chunk_size, int) and chunk_size > 0:
            return chunk_size

        return TARGET_CHUNK_SIZE

    except Exception as e:
        logger.exception(
            "Failed to retrieve cohort chunking config, disabling chunking",
            team_uuid=str(team_uuid),
            organization_id=organization_id,
            error=str(e),
        )
        return None
