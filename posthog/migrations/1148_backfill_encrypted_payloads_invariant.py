from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def backfill_encrypted_payloads_invariant(apps, schema_editor):
    """Clear has_encrypted_payloads on flags that aren't remote configurations.

    The two booleans were independently settable via the API and a frontend
    template-switch path, so a small number of rows ended up with
    has_encrypted_payloads=true while is_remote_configuration=false. The new
    model and serializer validation rejects this combination, so existing rows
    must be reconciled before validation can run for any save path.

    All known affected rows have empty `filters.payloads`, so flipping the bit
    off is lossless. Updates the FK queryset directly to skip ModelActivityMixin
    signals — this is a janitorial fix, not user activity.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    updated = (
        FeatureFlag.objects.filter(
            has_encrypted_payloads=True,
        )
        .exclude(
            is_remote_configuration=True,
        )
        .update(has_encrypted_payloads=False)
    )

    if updated:
        logger.info("backfill_encrypted_payloads_invariant", updated_flags=updated)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1147_columnconfiguration_order_by")]

    operations = [
        migrations.RunPython(
            backfill_encrypted_payloads_invariant,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
