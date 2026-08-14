from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import F, QuerySet

from posthog.dataclasses import frozen

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_group import DashboardGroup
from products.dashboards.backend.models.dashboard_tile import DashboardTile

if TYPE_CHECKING:
    from posthog.models import User


def is_anonymous_section(group: DashboardGroup) -> bool:
    return not (group.name or "").strip()


def normalize_section_name(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    return stripped or None


def lock_dashboard(dashboard: Dashboard) -> Dashboard:
    return Dashboard.objects.select_for_update().get(pk=dashboard.pk)


def content_tiles_qs(dashboard: Dashboard) -> QuerySet[DashboardTile]:
    return DashboardTile.objects.filter(dashboard=dashboard).exclude(deleted=True)


def ordered_groups(dashboard: Dashboard) -> list[DashboardGroup]:
    return list(DashboardGroup.all_teams.filter(dashboard=dashboard).order_by("position", "created_at"))


def renumber_section_positions(dashboard: Dashboard) -> None:
    for index, group in enumerate(ordered_groups(dashboard)):
        if group.position != index:
            group.position = index
            group.save(update_fields=["position"])


def _shift_positions_from(dashboard: Dashboard, insert_at: int) -> None:
    dashboard.groups.filter(position__gte=insert_at).update(position=F("position") + 1)


def wrap_ungrouped_tiles_as_anonymous_section(
    dashboard: Dashboard, user: User | None, position: int = 0
) -> DashboardGroup | None:
    ungrouped = list(content_tiles_qs(dashboard).filter(parent_group__isnull=True))
    if not ungrouped:
        return None
    insert_at = max(0, min(position, len(ordered_groups(dashboard))))
    _shift_positions_from(dashboard, insert_at)
    group = DashboardGroup.all_teams.create(
        dashboard=dashboard,
        team=dashboard.team,
        name=None,
        position=insert_at,
        created_by=user,
        last_modified_by=user,
    )
    DashboardTile.objects.filter(id__in=[tile.id for tile in ungrouped]).update(parent_group=group)
    return group


def create_section(
    dashboard: Dashboard,
    *,
    user: User | None,
    name: str | None,
    position: int | None,
    wrap_existing: bool = True,
) -> DashboardGroup:
    dashboard = lock_dashboard(dashboard)
    existing = ordered_groups(dashboard)
    if wrap_existing and not existing:
        wrap_ungrouped_tiles_as_anonymous_section(dashboard, user)
        existing = ordered_groups(dashboard)

    insert_at = len(existing) if position is None else max(0, min(position, len(existing)))
    _shift_positions_from(dashboard, insert_at)
    group = DashboardGroup.all_teams.create(
        dashboard=dashboard,
        team=dashboard.team,
        name=normalize_section_name(name),
        position=insert_at,
        created_by=user,
        last_modified_by=user,
    )
    renumber_section_positions(dashboard)
    group.refresh_from_db()
    return group


def move_section(dashboard: Dashboard, group: DashboardGroup, new_position: int) -> DashboardGroup:
    lock_dashboard(dashboard)
    wrap_ungrouped_tiles_as_anonymous_section(
        dashboard, group.last_modified_by, position=len(ordered_groups(dashboard))
    )
    remaining = [item for item in ordered_groups(dashboard) if item.id != group.id]
    insert_at = max(0, min(new_position, len(remaining)))
    remaining.insert(insert_at, group)
    groups_to_update: list[DashboardGroup] = []
    for index, item in enumerate(remaining):
        if item.position != index:
            item.position = index
            groups_to_update.append(item)
    if groups_to_update:
        DashboardGroup.all_teams.bulk_update(groups_to_update, ["position"])
    group.refresh_from_db()
    return group


def resolve_default_section(dashboard: Dashboard, user: User | None) -> DashboardGroup | None:
    groups = ordered_groups(dashboard)
    if not groups:
        return None
    last = groups[-1]
    if is_anonymous_section(last):
        return last
    return create_section(dashboard, user=user, name=None, position=None, wrap_existing=False)


def delete_emptied_anonymous_section(group: DashboardGroup) -> bool:
    if not is_anonymous_section(group):
        return False
    if content_tiles_qs(group.dashboard).filter(parent_group=group).exists():
        return False
    dashboard = group.dashboard
    group.delete()
    renumber_section_positions(dashboard)
    return True


def assign_tile_to_section(tile: DashboardTile, group: DashboardGroup | None) -> UUID | None:
    source_id = tile.parent_group_id
    tile.parent_group = group
    tile.save(update_fields=["parent_group"])
    if source_id is None or (group is not None and source_id == group.id):
        return None
    source = DashboardGroup.all_teams.filter(id=source_id).first()
    if source is None:
        return None
    if delete_emptied_anonymous_section(source):
        return source_id
    return None


def _tile_y(tile: dict[str, Any]) -> int:
    layouts = tile.get("layouts") or {}
    sm = layouts.get("sm") if isinstance(layouts, dict) else None
    if not isinstance(sm, dict):
        return 0
    try:
        return int(sm.get("y", 0))
    except (TypeError, ValueError):
        return 0


@frozen
class SectionPartition:
    name: str | None
    group_key: str | None
    tiles: list[dict[str, Any]]


def partition_tiles_into_sections(
    header_layouts: list[dict[str, Any]],
    tiles: list[dict[str, Any]],
) -> list[SectionPartition]:
    """Bucket content tiles into named groups and anonymous runs between them.

    Named membership is by `group_key`. Tiles with a missing or unknown key are
    placed by y relative to the sorted header ys, so ungrouped runs can sit
    between named groups. A template with no GROUP tiles returns no sections.
    """
    headers = sorted(header_layouts, key=_tile_y)
    if not headers:
        return []

    known_keys = {header.get("group_key") for header in headers if header.get("group_key")}
    members_by_key: dict[str, list[dict[str, Any]]] = {str(key): [] for key in known_keys}
    ungrouped: list[dict[str, Any]] = []
    for tile in tiles:
        key = tile.get("group_key")
        if key and key in members_by_key:
            members_by_key[key].append(tile)
        else:
            ungrouped.append(tile)

    ungrouped.sort(key=_tile_y)
    header_ys = [_tile_y(header) for header in headers]
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(len(headers) + 1)]
    for tile in ungrouped:
        y = _tile_y(tile)
        placed = False
        for index, header_y in enumerate(header_ys):
            if y < header_y:
                buckets[index].append(tile)
                placed = True
                break
        if not placed:
            buckets[-1].append(tile)

    sections: list[SectionPartition] = []
    for index, header in enumerate(headers):
        if buckets[index]:
            sections.append(SectionPartition(name=None, group_key=None, tiles=buckets[index]))
        group_key = header.get("group_key")
        sections.append(
            SectionPartition(
                name=normalize_section_name(header.get("name")) or "Group",
                group_key=str(group_key) if group_key else None,
                tiles=members_by_key.get(str(group_key), []) if group_key else [],
            )
        )
    if buckets[-1]:
        sections.append(SectionPartition(name=None, group_key=None, tiles=buckets[-1]))
    return sections
