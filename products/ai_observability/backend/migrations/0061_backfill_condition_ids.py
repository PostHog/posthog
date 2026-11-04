from uuid import uuid4

from django.db import migrations


def _condition_needs_id(condition):
    return isinstance(condition, dict) and not (isinstance(condition.get("id"), str) and condition["id"])


def _backfill_model(model):
    batch_size = 500
    updates = []
    for row in model.objects.all().iterator(chunk_size=batch_size):
        if not isinstance(row.conditions, list) or not any(_condition_needs_id(c) for c in row.conditions):
            continue
        row.conditions = [{**c, "id": str(uuid4())} if _condition_needs_id(c) else c for c in row.conditions]
        updates.append(row)
        if len(updates) >= batch_size:
            # bulk_update (not save) so the post_save reload-workers signal does not fire per row.
            model.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)
            updates = []

    if updates:
        model.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)


def backfill_condition_ids(apps, schema_editor):
    _backfill_model(apps.get_model("ai_observability", "Evaluation"))
    _backfill_model(apps.get_model("ai_observability", "Tagger"))


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0060_evaluationreport_running_count"),
    ]

    operations = [
        migrations.RunPython(backfill_condition_ids, migrations.RunPython.noop, elidable=True),
    ]
