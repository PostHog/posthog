from typing import Any

from django.db import migrations


def _layout_y(tile: Any) -> int:
    layouts = tile.layouts if isinstance(tile.layouts, dict) else {}
    sm = layouts.get("sm") or {}
    y = sm.get("y", 0)
    try:
        return int(y)
    except (TypeError, ValueError):
        return 0


def _group_y(group: Any, header_by_group_id: dict[Any, Any]) -> int:
    header = header_by_group_id.get(group.id)
    return _layout_y(header) if header is not None else 0


def migrate_dashboard_group_sections(apps: Any, schema_editor: Any) -> None:
    # Inlined from partition_tiles_into_sections: migrations must not import app code.
    Dashboard = apps.get_model("dashboards", "Dashboard")
    DashboardGroup = apps.get_model("dashboards", "DashboardGroup")
    DashboardTile = apps.get_model("dashboards", "DashboardTile")
    groups_manager = getattr(DashboardGroup, "all_teams", DashboardGroup.objects)

    dashboard_ids = groups_manager.values_list("dashboard_id", flat=True).distinct()
    for dashboard_id in dashboard_ids.iterator():
        dashboard = Dashboard.objects.get(id=dashboard_id)
        groups = list(groups_manager.filter(dashboard_id=dashboard_id))
        header_tiles = list(DashboardTile.objects.filter(dashboard_id=dashboard_id, dashboard_group_id__isnull=False))
        header_by_group_id = {tile.dashboard_group_id: tile for tile in header_tiles}

        sorted_groups = sorted(groups, key=lambda group, mapping=header_by_group_id: _group_y(group, mapping))
        ungrouped_tiles = list(
            DashboardTile.objects.filter(
                dashboard_id=dashboard_id,
                dashboard_group_id__isnull=True,
                parent_group_id__isnull=True,
                deleted=False,
            )
        )
        header_ys = [_group_y(group, header_by_group_id) for group in sorted_groups]
        anonymous_tiles_by_bucket: dict[int, list[Any]] = {}
        for tile in ungrouped_tiles:
            tile_y = _layout_y(tile)
            bucket = sum(header_y <= tile_y for header_y in header_ys)
            anonymous_tiles_by_bucket.setdefault(bucket, []).append(tile)

        section_entries: list[tuple[int, Any, list[Any]]] = [
            (_group_y(group, header_by_group_id), group, []) for group in sorted_groups
        ]
        for tiles in anonymous_tiles_by_bucket.values():
            group = groups_manager.create(
                dashboard_id=dashboard_id,
                team_id=dashboard.team_id,
                name=None,
                position=0,
            )
            section_entries.append((min(_layout_y(tile) for tile in tiles), group, tiles))

        section_entries.sort(key=lambda entry: (entry[0], entry[2] != []))
        groups_to_update = []
        tiles_to_update = []
        for position, (_, group, tiles) in enumerate(section_entries):
            group.position = position
            groups_to_update.append(group)
            for tile in tiles:
                tile.parent_group_id = group.id
                tiles_to_update.append(tile)

        groups_manager.bulk_update(groups_to_update, ["position"])
        if tiles_to_update:
            DashboardTile.objects.bulk_update(tiles_to_update, ["parent_group"])
        DashboardTile.objects.filter(id__in=[tile.id for tile in header_tiles]).delete()


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0019_dashboardgroup_position_and_nullable_name")]

    operations = [migrations.RunPython(migrate_dashboard_group_sections, migrations.RunPython.noop)]
