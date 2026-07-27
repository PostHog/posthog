from uuid import uuid4

from django.db import migrations

# Keys the EvaluationConditionSerializer accepts, plus the bytecode keys that
# Evaluation.save() writes onto each condition. Anything else (e.g. a legacy
# `sampling_rate`) is dropped during normalization.
_ALLOWED_KEYS = frozenset({"id", "rollout_percentage", "properties", "bytecode", "bytecode_error"})

# Keys of a PostHog property filter that some legacy rows stored at the condition's
# top level instead of nested inside `properties`.
_PROPERTY_FILTER_KEYS = ("key", "value", "operator", "type", "group_type_index")


def _condition_is_clean(condition):
    if not isinstance(condition, dict):
        return False
    if not (isinstance(condition.get("id"), str) and condition["id"]):
        return False
    rollout = condition.get("rollout_percentage")
    if isinstance(rollout, bool) or not isinstance(rollout, (int, float)):
        return False
    properties = condition.get("properties")
    if not isinstance(properties, list) or not all(isinstance(p, dict) for p in properties):
        return False
    return all(key in _ALLOWED_KEYS for key in condition)


def _conditions_need_fix(conditions):
    if not isinstance(conditions, list):
        return True
    return not all(_condition_is_clean(condition) for condition in conditions)


def _normalize_condition(condition):
    if not isinstance(condition, dict):
        return {"id": str(uuid4()), "rollout_percentage": 0, "properties": []}

    condition_id = condition.get("id")
    condition_id = condition_id if isinstance(condition_id, str) and condition_id else str(uuid4())

    rollout = condition.get("rollout_percentage")
    # Default a missing/invalid rollout to 0 (not 100) so a previously-dormant eval stays
    # dormant — these rows were never firing, and 100 would silently start them at full volume.
    if isinstance(rollout, bool) or not isinstance(rollout, (int, float)):
        rollout = 0

    raw_properties = condition.get("properties")
    properties = [p for p in raw_properties if isinstance(p, dict)] if isinstance(raw_properties, list) else []
    # Fold a property filter that leaked to the condition's top level back into `properties`.
    leaked_filter = {key: condition[key] for key in _PROPERTY_FILTER_KEYS if key in condition}
    if leaked_filter:
        properties.append(leaked_filter)

    normalized = {"id": condition_id, "rollout_percentage": rollout, "properties": properties}

    # Keep compiled filter bytecode only when `properties` is untouched; if we changed it,
    # drop the now-stale bytecode so the next save() recompiles it.
    if not leaked_filter and properties == raw_properties:
        for key in ("bytecode", "bytecode_error"):
            if key in condition:
                normalized[key] = condition[key]

    return normalized


def normalize_evaluation_conditions(apps, schema_editor):
    Evaluation = apps.get_model("ai_observability", "Evaluation")

    batch_size = 500
    updates = []
    for evaluation in Evaluation.objects.all().iterator(chunk_size=batch_size):
        conditions = evaluation.conditions
        if not _conditions_need_fix(conditions):
            continue
        source = conditions if isinstance(conditions, list) else []
        evaluation.conditions = [_normalize_condition(condition) for condition in source]
        updates.append(evaluation)
        if len(updates) >= batch_size:
            # bulk_update (not save) so the post_save reload-workers signal does not fire per row.
            Evaluation.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)
            updates = []

    if updates:
        Evaluation.objects.bulk_update(updates, ["conditions"], batch_size=batch_size)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0002_migrate_ai_observability_models"),
    ]

    operations = [
        migrations.RunPython(normalize_evaluation_conditions, migrations.RunPython.noop, elidable=True),
    ]
