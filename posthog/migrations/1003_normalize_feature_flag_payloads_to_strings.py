import json

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def normalize_payloads_to_strings(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    flags_with_payloads = FeatureFlag.objects.raw("""
        SELECT f.*
        FROM posthog_featureflag f,
             jsonb_each(f.filters->'payloads') AS kv(key, value)
        WHERE f.filters->'payloads' IS NOT NULL
          AND f.filters->'payloads' != '{}'::jsonb
          AND jsonb_typeof(kv.value) = 'object'
        GROUP BY f.id
    """)

    to_update = []
    for flag in flags_with_payloads:
        payloads = flag.filters.get("payloads", {})
        changed = False
        for key, value in payloads.items():
            if isinstance(value, dict):
                payloads[key] = json.dumps(value)
                changed = True
        if changed:
            flag.filters["payloads"] = payloads
            to_update.append(flag)

    if to_update:
        FeatureFlag.objects.bulk_update(to_update, ["filters"], batch_size=BATCH_SIZE)
        logger.info("normalized_feature_flag_payloads", count=len(to_update))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
    ]

    operations = [
        migrations.RunPython(normalize_payloads_to_strings, migrations.RunPython.noop, elidable=True),
    ]
