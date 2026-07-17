from django.core.paginator import Paginator
from django.db import migrations

import structlog


def backfill_button_tile_type(apps, _) -> None:
    """
    Older save-as-template rows stored a button tile as `{"button_tile": {...}}` with no
    top-level `type`, unlike text/insight/widget tiles which always had one. The template
    reader (`create_from_template`) used to hard-index `template_tile["type"]`, so instantiating
    one of these templates raised `KeyError: 'type'` and left a half-created dashboard behind.
    The reader and the frontend serializer are now both fixed, but rows saved before that fix
    still have the old shape sitting in the DB - this walks every DashboardTemplate and adds the
    missing `"type": "BUTTON"` in place, so those templates instantiate cleanly too.
    """
    logger = structlog.get_logger(__name__)
    DashboardTemplate = apps.get_model("dashboards", "DashboardTemplate")

    templates = DashboardTemplate.objects.order_by("id").all()
    paginator = Paginator(templates, 500)  # process in pages so a huge tiles list doesn't sit in memory all at once
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

        # One bulk_update per page: touches only the templates that actually needed a fix.
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
