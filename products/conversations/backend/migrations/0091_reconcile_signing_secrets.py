from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def reconcile_signing_secrets(apps, schema_editor):
    """
    Resync signing secret rows that drifted from the legacy token column (#66179).

    The widget verifier no longer reads Team.secret_api_token, and it trusts every
    SigningSecret row as is. A row that still mirrors the legacy column
    (rotated_independently=False) but holds a different value than the column means a
    rotation sync failed in the past: the stored value is a retired key, and trusting
    it would resurrect a revoked credential. Copy the column's current value over such
    rows, which is what the retired sync receiver would have written. Rows rotated
    independently are their own authority and are left alone. The legacy rotation path
    is deleted, so no new drift can appear after this runs.
    """
    SigningSecret = apps.get_model("conversations", "SigningSecret")

    checked = 0
    resynced = 0
    rows = SigningSecret.objects.filter(rotated_independently=False).select_related("team")
    for row in rows.iterator(chunk_size=BATCH_SIZE):
        checked += 1
        current_token = row.team.secret_api_token
        if not current_token:
            # The old verifier trusted a row with no legacy counterpart; nothing to resync.
            continue
        # EncryptedTextField ciphertext is non-deterministic, so compare decrypted values
        # in Python; a filter on the column cannot match.
        if row.secret == current_token and not row.previous_secret:
            continue
        # Conditional UPDATE instead of save(): a rotation that commits after the read
        # above sets rotated_independently=True under its row lock, and this write must
        # not clobber the secret it minted. The token column has no writers left, so the
        # read value cannot go stale the other way. A mirroring row never carries grace;
        # a drifted previous_secret may hold a revoked key, so expire it with the resync.
        resynced += SigningSecret.objects.filter(pk=row.pk, rotated_independently=False).update(
            secret=current_token,
            previous_secret=None,
            previous_secret_rotated_at=None,
        )

    logger.info("reconciled_conversations_signing_secrets", checked=checked, resynced=resynced)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0090_pylon_issue_uniq"),
    ]

    operations = [
        migrations.RunPython(reconcile_signing_secrets, migrations.RunPython.noop, elidable=True),
    ]
