"""Point a subject's table at staged (unpublished) files, for write-audit-publish check runs."""

from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql.database.database import Database
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.modifiers import create_default_modifiers_for_team

from products.data_modeling.backend.facade import api as data_modeling_facade

if TYPE_CHECKING:
    from posthog.models.team import Team


def build_staged_database(team: "Team", saved_query_id: str | UUID, staged_queryable_folder: str) -> Database | None:
    """None means there is no materialized table to repoint.

    Callers must not fall back to the unmodified database, which reads the live view and so rules
    on data the publish would not write.
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
