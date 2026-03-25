from django.db import migrations


def backfill_condition_aggregation(apps, schema_editor):
    """
    Ensure every condition set in every feature flag's filters has an explicit
    aggregation_group_type_index key. Person-aggregated flags previously omitted
    this key; now we set it to None so the frontend can use consistent null checks.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    batch_size = 500
    updated = []

    for flag in FeatureFlag.objects.filter(deleted=False).iterator(chunk_size=batch_size):
        filters = flag.filters or {}
        groups = filters.get("groups", [])
        flag_level = filters.get("aggregation_group_type_index")
        changed = False

        for group in groups:
            if "aggregation_group_type_index" not in group:
                group["aggregation_group_type_index"] = flag_level
                changed = True

        if "aggregation_group_type_index" not in filters:
            filters["aggregation_group_type_index"] = flag_level
            changed = True

        if changed:
            flag.filters = filters
            updated.append(flag)

        if len(updated) >= batch_size:
            FeatureFlag.objects.bulk_update(updated, ["filters"])
            updated = []

    if updated:
        FeatureFlag.objects.bulk_update(updated, ["filters"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1066_alter_insight_saved"),
    ]

    operations = [
        migrations.RunPython(
            backfill_condition_aggregation,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
