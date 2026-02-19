from django.db import migrations
from django.db.models import Q

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 100


def fix_legacy_feature_flag_filters(apps, schema_editor):
    """
    Backfill `filters` for ~1,235 legacy feature flags created before
    the `groups` structure was introduced.  After this migration every
    flag row is guaranteed to have `filters->'groups'`.

    Mirrors the fallback in FeatureFlag.get_filters() so the method
    can be simplified to just `return self.filters`.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    total = 0
    queryset = FeatureFlag.objects.filter(Q(filters__isnull=True) | ~Q(filters__has_key="groups"))

    while True:
        flags = list(queryset[:BATCH_SIZE])
        if not flags:
            break

        for flag in flags:
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

        FeatureFlag.objects.bulk_update(flags, ["filters"])
        total += len(flags)

    logger.info("Fixed legacy feature flag filters", updated_rows=total)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1014_increase_annotation_content_max_length"),
    ]

    operations = [
        migrations.RunPython(fix_legacy_feature_flag_filters, migrations.RunPython.noop, elidable=True),
    ]
