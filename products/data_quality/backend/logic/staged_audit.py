"""Point a subject's table at staged (unpublished) files, for write-audit-publish check runs.

A matview refresh stages its output into a new timestamped queryable folder before anything is
published; the publish is just repointing ``queryable_folder`` on the subject's warehouse table.
The audit therefore builds the team's HogQL database and swaps that one field on the in-memory
table object, so compiled checks read the staged version while every other table resolves normally.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql.database.database import Database
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.modifiers import create_default_modifiers_for_team

from products.data_modeling.backend.facade import api as data_modeling_facade

if TYPE_CHECKING:
    from posthog.models.team import Team


def build_staged_database(team: "Team", saved_query_id: str | UUID, staged_queryable_folder: str) -> Database | None:
    """A database whose subject table reads the staged folder instead of the published one.

    Returns None when there is no materialized table to repoint -- the first materialization, or a
    subject that no longer resolves. The caller must not fall back to the unmodified database: that
    reads the live view, which recomputes from upstreams that may have moved since the refresh, so
    its verdict describes data the publish would not produce.
    """
    summary = data_modeling_facade.get_saved_query_summary(team.pk, saved_query_id)
    if summary is None:
        return None

    modifiers = create_default_modifiers_for_team(team)
    database = Database.create_for(team=team, modifiers=modifiers)
    try:
        table = database.get_table(summary.name)
    except Exception:
        return None
    if not isinstance(table, S3Table):
        return None
    table.queryable_folder = staged_queryable_folder
    return database
