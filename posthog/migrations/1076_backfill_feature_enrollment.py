from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 250


def backfill_feature_enrollment(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    total_updated = 0
    objects_to_update = []

    queryset = FeatureFlag.objects.filter(
        deleted=False,
        filters__super_groups__isnull=False,
    ).exclude(
        filters__feature_enrollment=True,
    )

    for flag in queryset.iterator(chunk_size=BATCH_SIZE):
        try:
            super_groups = flag.filters.get("super_groups")
            if not isinstance(super_groups, list) or len(super_groups) == 0:
                continue

            flag.filters["feature_enrollment"] = True
            objects_to_update.append(flag)
        except Exception:
            logger.exception("backfill_feature_enrollment_error", flag_id=flag.id)

        if len(objects_to_update) >= BATCH_SIZE:
            FeatureFlag.objects.bulk_update(objects_to_update, ["filters"])
            total_updated += len(objects_to_update)
            objects_to_update = []

    if objects_to_update:
        FeatureFlag.objects.bulk_update(objects_to_update, ["filters"])
        total_updated += len(objects_to_update)

    if total_updated:
        logger.info("backfilled_feature_enrollment", updated_flags=total_updated)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1075_team_snippet_config"),
    ]

    operations = [
        migrations.RunPython(backfill_feature_enrollment, migrations.RunPython.noop, elidable=True),
    ]
