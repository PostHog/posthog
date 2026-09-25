"""Point a subject's table at staged (unpublished) files, for write-audit-publish check runs."""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select

from products.data_modeling.backend.facade import api as data_modeling_facade

from .compiler import print_check_query

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


@dataclass(frozen=True)
class StagedSubjectOverride:
    """Where a write-audit-publish run should read the subject from instead of the published table."""

    saved_query_id: str
    queryable_folder: str


def build_staged_database(
    team: "Team",
    saved_query_id: str | UUID,
    staged_queryable_folder: str,
    user: "User | None" = None,
    bypass_warehouse_access_control: bool = False,
) -> Database | None:
    """A database whose subject table reads the staged folder instead of the published one.

    Built with the run's ACL posture (the runner's ``_authorize``), so a staged audit enforces the
    same warehouse access control an unstaged run would.

    None means there is no materialized table to repoint. Callers must not fall back to the
    unmodified database, which reads the live view and so rules on data the publish would not write.
    """
    summary = data_modeling_facade.get_saved_query_summary(team.pk, saved_query_id)
    if summary is None:
        return None

    modifiers = create_default_modifiers_for_team(team)
    database = Database.create_for(
        team=team,
        user=user,
        modifiers=modifiers,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )
    try:
        table = database.get_table(summary.name)
    except Exception:
        return None
    if not isinstance(table, S3Table):
        return None
    table.queryable_folder = staged_queryable_folder
    return database


def replayable_failing_rows_query(
    team_id: int,
    saved_query_id: str | UUID,
    failing_rows: "ast.SelectQuery | ast.SelectSetQuery",
) -> str | None:
    """The failing-rows query with the view's definition inlined as a CTE, or None when the view cannot be read."""
    view_cte = _view_definition_cte(team_id, saved_query_id)
    if view_cte is None:
        return None
    return print_check_query(_with_cte(failing_rows, view_cte))


def _view_definition_cte(team_id: int, saved_query_id: str | UUID) -> ast.CTE | None:
    summary = data_modeling_facade.get_saved_query_summary(team_id, saved_query_id)
    definition = data_modeling_facade.get_saved_query_sql(team_id, saved_query_id)
    if summary is None or definition is None:
        return None
    try:
        parsed = parse_select(definition)
    except BaseHogQLError:
        return None
    return ast.CTE(name=summary.name, expr=parsed, cte_type="subquery")


def _with_cte(query: "ast.SelectQuery | ast.SelectSetQuery", cte: ast.CTE) -> ast.SelectQuery:
    if isinstance(query, ast.SelectSetQuery) or cte.name in (query.ctes or {}):
        return ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=query),
            ctes={cte.name: cte},
        )
    return replace(query, ctes={cte.name: cte, **(query.ctes or {})})
