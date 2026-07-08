from django.core.paginator import Paginator
from django.db import migrations

import structlog


def backfill_button_tile_type(apps, _) -> None:
    logger = structlog.get_logger(__name__)
    DashboardTemplate = apps.get_model("dashboards", "DashboardTemplate")

    templates = DashboardTemplate.objects.order_by("id").all()
    paginator = Paginator(templates, 500)
    updated_count = 0

    for page_number in paginator.page_range:
        updated_templates = []

        for template in paginator.page(page_number).object_list:
            if not template.tiles:
                continue

            changed = False
            for tile in template.tiles:
                if isinstance(tile, dict) and tile.get("button_tile") is not None and "type" not in tile:
                    tile["type"] = "BUTTON"
                    changed = True

            if changed:
                updated_templates.append(template)

        if updated_templates:
            DashboardTemplate.objects.bulk_update(updated_templates, ["tiles"])
            updated_count += len(updated_templates)

    logger.info("backfill_dashboardtemplate_button_tile_type_done", updated_count=updated_count)


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0013_dashboardtile_button_tile_id_idx"),
    ]

    operations = [
        migrations.RunPython(backfill_button_tile_type, reverse_code=migrations.RunPython.noop),
    ]
