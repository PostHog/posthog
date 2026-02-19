from django.db import migrations
from django.db.models import Q

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 300


def fix_legacy_feature_flag_filters(apps, schema_editor):
    """
    Backfill `filters` for ~1,235 legacy feature flags created before
    the `groups` structure was introduced.  After this migration every
    flag row is guaranteed to have `filters->'groups'`.

    Mirrors the fallback in FeatureFlag.get_filters() so the method
    can be simplified to just `return self.filters`.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    queryset = FeatureFlag.objects.filter(Q(filters__isnull=True) | ~Q(filters__has_key="groups"))

    total = 0
    batch: list = []
    for flag in queryset.iterator(chunk_size=BATCH_SIZE):
        existing = dict(flag.filters) if isinstance(flag.filters, dict) else {}
        properties = existing.pop("properties", [])
        flag.filters = {
            **existing,
            "groups": [
                {
                    "properties": properties,
                    "rollout_percentage": flag.rollout_percentage,
                }
            ],
        }
        batch.append(flag)

        if len(batch) >= BATCH_SIZE:
            FeatureFlag.objects.bulk_update(batch, ["filters"])
            total += len(batch)
            batch = []

    if batch:
        FeatureFlag.objects.bulk_update(batch, ["filters"])
        total += len(batch)

    logger.info("Fixed legacy feature flag filters", updated_rows=total)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1014_increase_annotation_content_max_length"),
    ]

    operations = [
        migrations.RunPython(fix_legacy_feature_flag_filters, migrations.RunPython.noop, elidable=True),
    ]
