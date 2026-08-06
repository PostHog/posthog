from __future__ import annotations

from typing import Any

import structlog

from posthog.models.resource_transfer.inter_project_transferer import duplicate_resource_to_new_team
from posthog.models.resource_transfer.resource_transfer import ResourceTransfer
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)


def copy_warehouse_views_by_name(
    *,
    view_names: set[str],
    source_team: Team,
    target_team: Team,
    created_by: User,
) -> dict[str, str]:
    """Copy the named data warehouse views from ``source_team`` into ``target_team``.

    Each view is copied with the resource-transfer engine, which also pulls in its upstream view
    dependencies and lands every copy unmaterialized. Names that don't resolve to a view in the source
    team (physical tables, source connections) are skipped — they need their own setup in the target.

    The copy does not bring the underlying source data across, so a copied view resolves but may return
    no rows until the target project has data behind it.

    Returns a ``{original_name: new_name}`` remap for any view that a name collision in the target forced
    to be renamed, so callers can repoint references at the new name. Views whose names were free keep
    them and are absent from the remap.
    """
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    source_views = list(DataWarehouseSavedQuery.objects.filter(team=source_team, name__in=view_names, deleted=False))
    if not source_views:
        return {}

    name_remap: dict[str, str] = {}
    for view in source_views:
        original_name = view.name
        duplicate_resource_to_new_team(view, target_team, created_by=created_by)
        new_name = _copied_view_name(source_pk=view.pk, target_team=target_team)
        if new_name and new_name != original_name:
            name_remap[original_name] = new_name

    logger.info(
        "resource_transfer.warehouse_views_copied_by_name",
        source_team_id=source_team.pk,
        target_team_id=target_team.pk,
        view_count=len(source_views),
        renamed=len(name_remap),
    )
    return name_remap


def _copied_view_name(*, source_pk: Any, target_team: Team) -> str | None:
    """Resolve the destination name of a just-copied view via its transfer record."""
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    record = (
        ResourceTransfer.objects.filter(
            resource_kind="DataWarehouseSavedQuery",
            resource_id=str(source_pk),
            destination_team=target_team,
        )
        .order_by("-last_transferred_at")
        .first()
    )
    if record is None:
        return None
    copy = DataWarehouseSavedQuery.objects.filter(pk=record.duplicated_resource_id).first()
    return copy.name if copy else None
