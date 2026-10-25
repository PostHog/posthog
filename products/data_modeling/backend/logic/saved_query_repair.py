import copy
import hashlib
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction

import structlog

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import FindPlaceholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Detail, Trigger, changes_between, log_activity
from posthog.models.scoping import team_scope

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import (
    SavedQueryRepairConflictError,
    SavedQueryRepairForbiddenError,
    SavedQueryRepairInvalidError,
    SavedQueryRepairNotFoundError,
    SavedQueryRepairPlan,
    SavedQueryRepairUnsupportedError,
    SavedQueryRepairValidation,
)
from ..facade.modeling import ResolutionCycleError, get_parents_from_model_query
from ..models.datawarehouse_saved_query import DataWarehouseSavedQuery
from .incremental import IncrementalConfig
from .incremental_eligibility import check_incremental_eligibility, definition_database
from .saved_query_dag_sync import adopt_saved_query_without_edges, sync_saved_query_to_dag

if TYPE_CHECKING:
    from posthog.models import User

LOGGER = structlog.get_logger(__name__)

QUERY_CHANGED = (
    "This view changed after the SQL repair was proposed. Review the current query before you create a new repair "
    "suggestion."
)
SCHEMA_CHANGED = (
    "The proposed query changes the result schema. SQL repair suggestions must keep the same columns and types."
)
MANAGED_VIEW = "Managed views do not support SQL repair suggestions."
NO_SCHEMA = "This view has no saved result schema to compare with the proposed query."
SAME_QUERY = "The proposed query is the same as the current query."


@frozen
class _PreparedSavedQueryRepair:
    plan: SavedQueryRepairPlan
    columns: dict[str, dict[str, Any]]
    external_tables: list[str] | None


def prepare_saved_query_repair(
    team_id: int, saved_query_id: UUID, proposed_query: str, *, user: "User"
) -> SavedQueryRepairPlan:
    return _prepare_saved_query_repair(team_id, saved_query_id, proposed_query, user=user).plan


def _prepare_saved_query_repair(
    team_id: int, saved_query_id: UUID, proposed_query: str, *, user: "User"
) -> _PreparedSavedQueryRepair:
    saved_query = _live_saved_query(team_id, saved_query_id)
    _require_read_access(saved_query, user)
    if saved_query.managed_viewset_id is not None:
        raise SavedQueryRepairUnsupportedError(MANAGED_VIEW)
    if not isinstance(saved_query.query, dict) or not isinstance(saved_query.query.get("query"), str):
        raise SavedQueryRepairUnsupportedError("This view has no SQL query to repair.")
    original_query = cast(str, saved_query.query["query"])
    if proposed_query.strip() == original_query.strip():
        raise SavedQueryRepairInvalidError(SAME_QUERY)

    database = definition_database(team_id, user=user)
    columns, external_tables = _validate_proposed_query(saved_query, proposed_query, user=user, database=database)
    _require_same_schema(saved_query, columns)
    _require_incremental_compatibility(saved_query, proposed_query, columns, database)

    plan = SavedQueryRepairPlan(
        saved_query_id=saved_query.id,
        subject_name=saved_query.name,
        original_query=original_query,
        original_query_revision=str(saved_query.query_revision) if saved_query.query_revision else None,
        original_query_hash=_query_hash(original_query),
        proposed_query=proposed_query,
        validation=SavedQueryRepairValidation(
            syntax_valid=True,
            references_valid=True,
            result_schema_compatible=True,
            read_only=True,
            rows_read=0,
            business_equivalence_checked=False,
        ),
    )
    return _PreparedSavedQueryRepair(plan=plan, columns=columns, external_tables=external_tables)


def apply_saved_query_repair(
    team_id: int,
    saved_query_id: UUID,
    *,
    original_query_revision: str | None,
    original_query_hash: str,
    proposed_query: str,
    user: "User",
    was_impersonated: bool,
    trigger: Trigger,
) -> str:
    prepared = _prepare_saved_query_repair(team_id, saved_query_id, proposed_query, user=user)
    plan = prepared.plan
    if plan.original_query_revision != original_query_revision or plan.original_query_hash != original_query_hash:
        raise SavedQueryRepairConflictError(QUERY_CHANGED)

    with transaction.atomic():
        try:
            locked = (
                DataWarehouseSavedQuery.objects.select_for_update(no_key=True)
                .filter(team_id=team_id, id=saved_query_id)
                .exclude(deleted=True)
                .get()
            )
        except DataWarehouseSavedQuery.DoesNotExist:
            raise SavedQueryRepairNotFoundError()
        _require_edit_access(locked, user)
        current_query = (locked.query or {}).get("query") if isinstance(locked.query, dict) else None
        current_revision = str(locked.query_revision) if locked.query_revision else None
        if (
            not isinstance(current_query, str)
            or current_revision != original_query_revision
            or _query_hash(current_query) != original_query_hash
        ):
            raise SavedQueryRepairConflictError(QUERY_CHANGED)
        if locked.managed_viewset_id is not None:
            raise SavedQueryRepairUnsupportedError(MANAGED_VIEW)

        before_update = copy.copy(locked)
        locked.apply_query_update(
            {"kind": "HogQLQuery", "query": proposed_query},
            columns=prepared.columns,
            external_tables=prepared.external_tables,
        )
        with team_scope(locked.team_id):
            changes = changes_between("DataWarehouseSavedQuery", previous=before_update, current=locked)
        log_activity(
            organization_id=locked.team.organization_id,
            team_id=locked.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=locked.id,
            scope="DataWarehouseSavedQuery",
            activity="updated",
            detail=Detail(
                name=locked.name,
                changes=changes,
                trigger=trigger,
            ),
        )
        try:
            with transaction.atomic():
                sync_saved_query_to_dag(locked)
        except Exception as error:
            LOGGER.exception("Failed to sync repaired saved query to DAG", saved_query_id=str(locked.id))
            adopt_saved_query_without_edges(locked.team_id, locked.id, _lineage_error(error))
    return str(locked.query_revision)


def _live_saved_query(team_id: int, saved_query_id: UUID) -> DataWarehouseSavedQuery:
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id)
        .exclude(deleted=True)
        .select_related("team")
        .first()
    )
    if saved_query is None:
        raise SavedQueryRepairNotFoundError()
    return saved_query


def _require_edit_access(saved_query: DataWarehouseSavedQuery, user: "User") -> None:
    if not UserAccessControl(user=user, team=saved_query.team).check_access_level_for_object(saved_query, "editor"):
        raise SavedQueryRepairForbiddenError("You need edit access to this view to apply its SQL repair.")


def _require_read_access(saved_query: DataWarehouseSavedQuery, user: "User") -> None:
    if not UserAccessControl(user=user, team=saved_query.team).check_access_level_for_object(saved_query, "viewer"):
        raise SavedQueryRepairForbiddenError("You need read access to this view to propose its SQL repair.")


def _validate_proposed_query(
    saved_query: DataWarehouseSavedQuery,
    proposed_query: str,
    *,
    user: "User",
    database: Database,
) -> tuple[dict[str, dict[str, Any]], list[str] | None]:
    _validate_query_syntax(saved_query.team_id, proposed_query, user=user)
    probe = DataWarehouseSavedQuery(
        team=saved_query.team,
        name=saved_query.name,
        query={"kind": "HogQLQuery", "query": proposed_query},
    )
    try:
        get_parents_from_model_query(saved_query.team, saved_query.name, proposed_query, database=database)
        return probe.get_columns(user=user), probe.get_s3_tables(database=database)
    except (RecursionError, ResolutionCycleError):
        raise SavedQueryRepairInvalidError("The proposed query creates a view cycle.")
    except Exception as error:
        if isinstance(error, ExposedHogQLError):
            raise SavedQueryRepairInvalidError(f"The proposed query has an invalid reference: {error}")
        raise SavedQueryRepairInvalidError(
            f"The proposed query failed the read-only check with {type(error).__name__}."
        )


def _validate_query_syntax(team_id: int, query: str, *, user: "User") -> None:
    if not query.strip():
        raise SavedQueryRepairInvalidError("The proposed query is empty.")
    try:
        select_ast = parse_select(query)
        placeholders = FindPlaceholders()
        placeholders.visit(select_ast)
    except (ExposedHogQLError, ValueError) as error:
        raise SavedQueryRepairInvalidError(f"The proposed query has invalid syntax: {error}")
    if placeholders.placeholder_fields or placeholders.placeholder_expressions or placeholders.has_filters:
        raise SavedQueryRepairUnsupportedError("SQL repair suggestions cannot use variables, filters, or placeholders.")
    try:
        prepare_and_print_ast(
            node=select_ast,
            context=HogQLContext(team_id=team_id, user=user, enable_select_queries=True),
            dialect="clickhouse",
            stack=None,
            settings=None,
        )
    except Exception as error:
        if isinstance(error, ExposedHogQLError):
            raise SavedQueryRepairInvalidError(f"The proposed query is invalid: {error}")
        if not settings.DEBUG:
            raise SavedQueryRepairInvalidError(f"The proposed query is invalid: {type(error).__name__}")
        raise


def _require_same_schema(saved_query: DataWarehouseSavedQuery, proposed_columns: dict[str, dict[str, Any]]) -> None:
    current_columns = saved_query.columns or {}
    if not current_columns:
        raise SavedQueryRepairUnsupportedError(NO_SCHEMA)
    current_order = saved_query.column_order or list(current_columns)
    current_schema = [(name, _column_type(current_columns.get(name))) for name in current_order]
    proposed_schema = [(name, _column_type(value)) for name, value in proposed_columns.items()]
    if current_schema != proposed_schema:
        raise SavedQueryRepairInvalidError(SCHEMA_CHANGED)


def _require_incremental_compatibility(
    saved_query: DataWarehouseSavedQuery,
    proposed_query: str,
    columns: dict[str, dict[str, Any]],
    database: Database,
) -> None:
    config = saved_query.incremental_config
    if not isinstance(config, dict) or not config.get("enabled"):
        return
    incremental_key = config.get("incremental_key")
    unique_key = config.get("unique_key")
    if not isinstance(incremental_key, str) or not isinstance(unique_key, list):
        raise SavedQueryRepairUnsupportedError("This view has unsupported incremental settings.")
    result = check_incremental_eligibility(
        proposed_query,
        IncrementalConfig(
            incremental_key=incremental_key,
            unique_key=tuple(str(key) for key in unique_key),
            lookback_seconds=int(config.get("lookback_seconds", 0)),
        ),
        column_types={name: str(value.get("clickhouse")) for name, value in columns.items()},
        database=database,
    )
    if not result.eligible:
        raise SavedQueryRepairInvalidError(
            "The proposed query is not compatible with this view's incremental settings."
        )


def _column_type(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("clickhouse")
    return str(value) if value is not None else None


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def _lineage_error(error: Exception) -> str:
    return (
        str(error) if isinstance(error, ExposedHogQLError) else "Could not build this view's lineage after its update."
    )
