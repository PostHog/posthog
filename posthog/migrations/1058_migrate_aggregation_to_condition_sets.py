from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 300


def migrate_aggregation_to_condition_sets(apps, schema_editor):
    """
    Copy each flag's top-level `aggregation_group_type_index` into every
    condition set (filters["groups"][N]) so that each condition set carries
    its own aggregation mode. Flags without the field get `null` explicitly
    on each condition set for consistency.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    queryset = FeatureFlag.objects.filter(filters__has_key="groups").exclude(filters__isnull=True)

    total = 0
    batch: list = []
    for flag in queryset.iterator(chunk_size=BATCH_SIZE):
        try:
            filters = flag.filters
            if not isinstance(filters, dict):
                continue

            groups = filters.get("groups")
            if not isinstance(groups, list) or not groups:
                continue

            flag_level_aggregation = filters.get("aggregation_group_type_index", None)

            # Skip flags where all condition sets already have the field set
            needs_update = any(
                "aggregation_group_type_index" not in group for group in groups if isinstance(group, dict)
            )
            if not needs_update:
                continue

            for group in groups:
                if isinstance(group, dict) and "aggregation_group_type_index" not in group:
                    group["aggregation_group_type_index"] = flag_level_aggregation

            flag.filters = filters
            batch.append(flag)

            if len(batch) >= BATCH_SIZE:
                FeatureFlag.objects.bulk_update(batch, ["filters"])
                total += len(batch)
                batch = []
        except Exception:
            logger.exception("Failed to migrate aggregation for flag", flag_id=flag.id)
            continue

    if batch:
        FeatureFlag.objects.bulk_update(batch, ["filters"])
        total += len(batch)

    logger.info("Migrated aggregation_group_type_index to condition sets", updated_rows=total)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1057_personalapikey_scopes_not_null"),
    ]

    operations = [
        migrations.RunPython(migrate_aggregation_to_condition_sets, migrations.RunPython.noop, elidable=True),
    ]
