from uuid import uuid4

from django.db import migrations


def _repair_condition(condition):
    if not isinstance(condition, dict):
        return condition, False

    repaired = {**condition}
    if not (isinstance(repaired.get("id"), str) and repaired["id"]):
        repaired["id"] = str(uuid4())
    rollout = repaired.get("rollout_percentage")
    # The scheduler never samples a set without a numeric rollout, so 0 keeps such a set dormant
    # instead of starting it at full volume.
    if isinstance(rollout, bool) or not isinstance(rollout, (int, float)):
        repaired["rollout_percentage"] = 0
    # A missing `properties` already compiled to match-all bytecode, so an empty list keeps the bytecode valid.
    if not isinstance(repaired.get("properties"), list):
        repaired["properties"] = []
    return repaired, repaired != condition


def _repair_model(model):
    batch_size = 500
    updates = []
    for row in model.objects.all().iterator(chunk_size=batch_size):
        if not isinstance(row.conditions, list):
            continue
        results = [_repair_condition(condition) for condition in row.conditions]
        if not any(changed for _, changed in results):
            continue
        row.conditions = [condition for condition, _ in results]
        updates.append(row)
        if len(updates) >= batch_size:
            # bulk_update (not save) so the post_save reload-workers signal does not fire per row.
            model.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)
            updates = []

    if updates:
        model.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)


def repair_condition_sets(apps, schema_editor):
    _repair_model(apps.get_model("ai_observability", "Evaluation"))
    _repair_model(apps.get_model("ai_observability", "Tagger"))


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0060_evaluationreport_running_count"),
    ]

    operations = [
        migrations.RunPython(repair_condition_sets, migrations.RunPython.noop, elidable=True),
    ]
