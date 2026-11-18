from django.db import migrations, transaction

import structlog

from posthog.models.utils import generate_random_token, hash_key_value

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

    A token that leak revocation retired (RevokedTeamSecretToken) must not become the
    trusted signing secret either, even when the row already mirrors it: such rows get
    a fresh random secret instead, so identity verification fails closed until an admin
    reads the new value from Conversations settings.
    """
    SigningSecret = apps.get_model("conversations", "SigningSecret")
    RevokedTeamSecretToken = apps.get_model("posthog", "RevokedTeamSecretToken")
    Team = SigningSecret._meta.get_field("team").related_model
    alias = schema_editor.connection.alias

    def is_revoked(team_id, token):
        return (
            RevokedTeamSecretToken.objects.using(alias)
            .filter(team_id=team_id, secure_value=hash_key_value(token))
            .exists()
        )

    checked = 0
    resynced = 0
    rows = (
        SigningSecret.objects.using(alias)
        .filter(rotated_independently=False)
        .select_related("team")
        .only("id", "secret", "previous_secret", "team", "team__secret_api_token")
    )
    for row in rows.iterator(chunk_size=BATCH_SIZE):
        checked += 1
        # EncryptedTextField ciphertext is non-deterministic, so compare decrypted values
        # in Python; a filter on the column cannot match.
        current_token = row.team.secret_api_token
        if not current_token:
            # The old verifier trusted a row with no legacy counterpart; nothing to resync.
            continue
        if row.secret == current_token and not row.previous_secret and not is_revoked(row.team_id, current_token):
            continue
        with transaction.atomic(using=alias):
            # A pod on the previous release can still rotate the legacy token under the
            # team row lock; lock the team and re-read so this write cannot copy a token
            # that rotation just retired.
            current_token = (
                Team.objects.using(alias).select_for_update(no_key=True).get(pk=row.team_id).secret_api_token
            )
            if not current_token:
                continue
            updates = {
                "secret": current_token,
                "previous_secret": None,
                "previous_secret_rotated_at": None,
            }
            if is_revoked(row.team_id, current_token):
                updates["secret"] = generate_random_token()
                # The row no longer mirrors the column; a rerun must not re-mint.
                updates["rotated_independently"] = True
            # Conditional UPDATE instead of save(): an independent rotation that commits
            # after the reads above sets rotated_independently=True under its row lock,
            # and this write must not clobber the secret it minted. A mirroring row never
            # carries grace; a drifted previous_secret may hold a revoked key, so expire
            # it with the resync.
            resynced += (
                SigningSecret.objects.using(alias).filter(pk=row.pk, rotated_independently=False).update(**updates)
            )

    logger.info("reconciled_conversations_signing_secrets", checked=checked, resynced=resynced)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0090_pylon_issue_uniq"),
        ("posthog", "1393_revokedteamsecrettoken"),
    ]

    operations = [
        migrations.RunPython(reconcile_signing_secrets, migrations.RunPython.noop, elidable=True),
    ]
