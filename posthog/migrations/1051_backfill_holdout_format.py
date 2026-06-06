from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def backfill_holdout_format(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    flags_to_update = []

    for flag in (
        FeatureFlag.objects.filter(
            deleted=False,
            filters__has_key="holdout_groups",
        )
        .exclude(filters__holdout_groups=None)
        .iterator(chunk_size=100)
    ):
        holdout_groups = flag.filters.get("holdout_groups")
        if not holdout_groups or flag.filters.get("holdout"):
            continue

        if not isinstance(holdout_groups, list) or len(holdout_groups) == 0:
            continue

        condition = holdout_groups[0]
        variant = condition.get("variant", "")
        # Parse holdout ID from variant string "holdout-{id}"
        try:
            holdout_id = int(variant.split("-", 1)[1]) if "-" in variant else None
        except (ValueError, IndexError):
            holdout_id = None
        if holdout_id is None:
            continue

        flag.filters["holdout"] = {
            "id": holdout_id,
            "exclusion_percentage": condition.get("rollout_percentage", 100),
        }
        flag.filters = flag.filters  # mark JSONField dirty for bulk_update
        flags_to_update.append(flag)

    if flags_to_update:
        FeatureFlag.objects.bulk_update(flags_to_update, ["filters"])
        logger.info("backfilled_holdout_format", updated_flags=len(flags_to_update))


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1050_rename_slack_twig_to_posthog_code"),
    ]

    operations = [
        migrations.RunPython(backfill_holdout_format, migrations.RunPython.noop, elidable=True),
    ]
