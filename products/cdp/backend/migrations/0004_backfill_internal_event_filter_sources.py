from django.db import migrations

BATCH_SIZE = 1000


def set_internal_event_sources(apps, schema_editor):
    HogFunction = apps.get_model("cdp", "HogFunction")
    db_alias = schema_editor.connection.alias
    functions_to_update = []

    for row in (
        HogFunction.objects.using(db_alias)
        .filter(type="internal_destination")
        .order_by("pk")
        .values("pk", "filters")
        .iterator(chunk_size=BATCH_SIZE)
    ):
        filters = row["filters"]
        # The column is nullable, and rows predating the filter UI hold null or a bare list.
        if not isinstance(filters, dict):
            continue
        events = filters.get("events")
        has_explicit_events = (
            isinstance(events, list)
            and bool(events)
            and all(
                isinstance(event, dict) and isinstance(event.get("id"), str) and bool(event["id"].strip())
                for event in events
            )
        )
        has_unsupported_filters = any(
            value is not None and (not isinstance(value, list) or bool(value))
            for value in (filters.get("actions"), filters.get("data_warehouse"))
        )
        if not has_explicit_events or has_unsupported_filters or filters.get("source") == "internal-events":
            continue

        functions_to_update.append(HogFunction(pk=row["pk"], filters={**filters, "source": "internal-events"}))
        if len(functions_to_update) == BATCH_SIZE:
            HogFunction.objects.using(db_alias).bulk_update(functions_to_update, ["filters"], batch_size=BATCH_SIZE)
            functions_to_update = []

    if functions_to_update:
        HogFunction.objects.using(db_alias).bulk_update(functions_to_update, ["filters"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
    ]

    operations = [
        migrations.RunPython(set_internal_event_sources, migrations.RunPython.noop),
    ]
