import json

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def normalize_payloads_to_strings(apps, schema_editor):
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")

    flags_with_payloads = FeatureFlag.objects.raw("""
        SELECT *
        FROM posthog_featureflag
        WHERE filters->'payloads' IS NOT NULL
          AND filters->'payloads' != '{}'::jsonb
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
        FeatureFlag.objects.bulk_update(to_update, ["filters"])
        logger.info("normalized_feature_flag_payloads", count=len(to_update))


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
    ]

    operations = [
        migrations.RunPython(normalize_payloads_to_strings, migrations.RunPython.noop, elidable=True),
    ]
