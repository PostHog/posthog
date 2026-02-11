import json

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def normalize_payloads_to_strings(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    # Only fetch flags where at least one payload value is a JSON object.
    # Other non-string types (number, boolean, array, null) are left as-is.
    flags_with_object_payloads = FeatureFlag.objects.raw("""
        SELECT f.id
        FROM posthog_featureflag f,
             jsonb_each(f.filters->'payloads') AS kv(key, value)
        WHERE f.filters->'payloads' IS NOT NULL
          AND f.filters->'payloads' != '{}'::jsonb
          AND jsonb_typeof(kv.value) = 'object'
        GROUP BY f.id
    """)

    updated = 0
    for flag in flags_with_object_payloads:
        flag = FeatureFlag.objects.get(pk=flag.id)
        payloads = flag.filters.get("payloads", {})
        for key, value in payloads.items():
            if isinstance(value, dict):
                payloads[key] = json.dumps(value)
        flag.filters["payloads"] = payloads
        flag.save(update_fields=["filters"])
        updated += 1

    if updated:
        logger.info("normalized_feature_flag_payloads", count=updated)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
    ]

    operations = [
        migrations.RunPython(normalize_payloads_to_strings, migrations.RunPython.noop, elidable=True),
    ]
