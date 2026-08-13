from typing import Any

from django.db import migrations


def _layout_y(tile: Any) -> int:
    layouts = tile.layouts if isinstance(tile.layouts, dict) else {}
    sm = layouts.get("sm") or {}
    y = sm.get("y", 0)
    return y if isinstance(y, int) else 0


def migrate_dashboard_group_sections(apps: Any, schema_editor: Any) -> None:
    Dashboard = apps.get_model("dashboards", "Dashboard")
    DashboardGroup = apps.get_model("dashboards", "DashboardGroup")
    DashboardTile = apps.get_model("dashboards", "DashboardTile")

    dashboard_ids = DashboardGroup.all_teams.values_list("dashboard_id", flat=True).distinct()
    for dashboard_id in dashboard_ids.iterator():
        dashboard = Dashboard.objects.get(id=dashboard_id)
        groups = list(DashboardGroup.all_teams.filter(dashboard_id=dashboard_id))
        header_tiles = list(DashboardTile.objects.filter(dashboard_id=dashboard_id, dashboard_group_id__isnull=False))
        header_by_group_id = {tile.dashboard_group_id: tile for tile in header_tiles}
        legacy_groups = sorted(
            (group for group in groups if group.id in header_by_group_id),
            key=lambda group: _layout_y(header_by_group_id[group.id]),
        )
        section_groups = sorted(
            (group for group in groups if group.id not in header_by_group_id),
            key=lambda group: (group.position, group.created_at),
        )

        ungrouped_tiles = list(
            DashboardTile.objects.filter(
                dashboard_id=dashboard_id,
                dashboard_group_id__isnull=True,
                parent_group_id__isnull=True,
            ).exclude(deleted=True)
        )
        anonymous_tiles_by_bucket: dict[int, list[Any]] = {}
        header_ys = [_layout_y(header_by_group_id[group.id]) for group in legacy_groups]
        for tile in ungrouped_tiles:
            tile_y = _layout_y(tile)
            bucket = sum(header_y <= tile_y for header_y in header_ys)
            anonymous_tiles_by_bucket.setdefault(bucket, []).append(tile)

        section_entries = [(_layout_y(header_by_group_id[group.id]), group, []) for group in legacy_groups]
        section_position_offset = max(header_ys, default=-1) + 1
        section_entries.extend((section_position_offset + group.position, group, []) for group in section_groups)
        for tiles in anonymous_tiles_by_bucket.values():
            group = DashboardGroup.all_teams.create(
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

        DashboardGroup.all_teams.bulk_update(groups_to_update, ["position"])
        if tiles_to_update:
            DashboardTile.objects.bulk_update(tiles_to_update, ["parent_group"])
        DashboardTile.objects.filter(id__in=[tile.id for tile in header_tiles]).delete()


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0019_dashboardgroup_position_and_nullable_name")]

    operations = [migrations.RunPython(migrate_dashboard_group_sections, migrations.RunPython.noop)]
