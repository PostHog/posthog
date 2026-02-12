import json

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def normalize_payloads_to_strings(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    total_updated = 0
    while True:
        flags_with_payloads = list(
            FeatureFlag.objects.raw(f"""
            SELECT f.*
            FROM posthog_featureflag f,
                 jsonb_each(f.filters->'payloads') AS kv(key, value)
            WHERE f.filters->'payloads' IS NOT NULL
              AND f.filters->'payloads' != '{{}}'::jsonb
              AND jsonb_typeof(kv.value) = 'object'
            GROUP BY f.id
            LIMIT {BATCH_SIZE}
        """)
        )

        if not flags_with_payloads:
            break

        for flag in flags_with_payloads:
            payloads = flag.filters.get("payloads", {})
            for key, value in payloads.items():
                if isinstance(value, dict):
                    payloads[key] = json.dumps(value)
            flag.filters["payloads"] = payloads

        FeatureFlag.objects.bulk_update(flags_with_payloads, ["filters"], batch_size=BATCH_SIZE)
        total_updated += len(flags_with_payloads)

    if total_updated:
        logger.info("normalized_feature_flag_payloads", count=total_updated)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
    ]

    operations = [
        migrations.RunPython(normalize_payloads_to_strings, migrations.RunPython.noop, elidable=True),
    ]
