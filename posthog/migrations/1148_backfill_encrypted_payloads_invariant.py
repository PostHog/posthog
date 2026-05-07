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

    Verified for PostHog Cloud (US: 8 rows, EU: 3 rows) that all violating
    rows have empty `filters.payloads`, so the bit-flip is lossless there.
    For self-hosted installs the same may not hold: a row with non-empty
    `filters.payloads.true` would, after the flip, expose its previously
    redacted ciphertext as a normal payload (redaction in to_representation
    is gated on has_encrypted_payloads). To stay safe-by-construction we
    partition the candidates and only flip rows whose `filters.payloads.true`
    is empty/null. Anything with a non-empty value is left in place and
    surfaced via a warning log for manual reconciliation.

    Updates the FK queryset directly to skip ModelActivityMixin signals —
    this is a janitorial fix, not user activity.
    """
    FeatureFlag = apps.get_model("posthog", "FeatureFlag")
    candidates = FeatureFlag.objects.filter(has_encrypted_payloads=True).exclude(is_remote_configuration=True)

    safe_to_clear = []
    needs_review = []
    for flag_id, filters in candidates.values_list("id", "filters"):
        true_payload = ((filters or {}).get("payloads") or {}).get("true")
        if not true_payload:
            safe_to_clear.append(flag_id)
        else:
            needs_review.append(flag_id)

    if needs_review:
        logger.warning(
            "backfill_encrypted_payloads_invariant_skipped",
            skipped_flag_ids=needs_review[:50],
            skipped_count=len(needs_review),
        )

    updated = FeatureFlag.objects.filter(id__in=safe_to_clear).update(has_encrypted_payloads=False)

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
