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
    reads the new value from Conversations settings. Revocations are re-read per batch
    and again after each repair locks the team row, because pods on the previous release
    record them without retiring the signing secret while this scan runs.
    """
    SigningSecret = apps.get_model("conversations", "SigningSecret")
    RevokedTeamSecretToken = apps.get_model("posthog", "RevokedTeamSecretToken")
    Team = apps.get_model("posthog", "Team")
    alias = schema_editor.connection.alias

    row_ids = list(SigningSecret.objects.using(alias).filter(rotated_independently=False).values_list("pk", flat=True))

    checked = 0
    resynced = 0
    # Minting a fresh secret breaks a team's widget identity verification until its admin
    # reads the new value, so the summary log names those teams for the operator.
    failed_closed_team_ids = []
    for start in range(0, len(row_ids), BATCH_SIZE):
        batch = list(
            SigningSecret.objects.using(alias)
            .filter(pk__in=row_ids[start : start + BATCH_SIZE], rotated_independently=False)
            .select_related("team")
            .only("id", "secret", "previous_secret", "team", "team__secret_api_token")
        )
        batch_revoked = set(
            RevokedTeamSecretToken.objects.using(alias)
            .filter(team_id__in=[row.team_id for row in batch])
            .values_list("team_id", "secure_value")
        )
        for row in batch:
            checked += 1
            # EncryptedTextField ciphertext is non-deterministic, so compare decrypted
            # values in Python; a filter on the column cannot match.
            current_token = row.team.secret_api_token
            if not current_token:
                # The old verifier trusted a row with no legacy counterpart; nothing to resync.
                continue
            if (
                row.secret == current_token
                and not row.previous_secret
                and (row.team_id, hash_key_value(current_token)) not in batch_revoked
            ):
                continue
            replaced_fail_closed = False
            # One short transaction per repaired row (the migration is non-atomic), so a
            # resync's team lock never blocks other teams' writes for the rest of the scan.
            with transaction.atomic(using=alias):
                # A pod on the previous release can still rotate the legacy token under
                # the team row lock; lock the team and re-read so this write cannot copy
                # a token that rotation just retired.
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
                token_revoked = (
                    RevokedTeamSecretToken.objects.using(alias)
                    .filter(team_id=row.team_id, secure_value=hash_key_value(current_token))
                    .exists()
                )
                if token_revoked:
                    updates["secret"] = generate_random_token()
                    # The row no longer mirrors the column; a rerun must not re-mint.
                    updates["rotated_independently"] = True
                # Conditional UPDATE instead of save(): an independent rotation that
                # commits after the reads above sets rotated_independently=True under its
                # row lock, and this write must not clobber the secret it minted. A
                # mirroring row never carries grace; a drifted previous_secret may hold a
                # revoked key, so expire it with the resync.
                updated = (
                    SigningSecret.objects.using(alias).filter(pk=row.pk, rotated_independently=False).update(**updates)
                )
                resynced += updated
                replaced_fail_closed = bool(updated) and token_revoked
            if replaced_fail_closed:
                failed_closed_team_ids.append(row.team_id)
                # Logged per commit: a restarted run skips already-repaired rows, so the
                # summary alone would lose teams replaced before the restart.
                logger.info("replaced_revoked_conversations_signing_secret", team_id=row.team_id)

    logger.info(
        "reconciled_conversations_signing_secrets",
        checked=checked,
        resynced=resynced,
        failed_closed_team_ids=failed_closed_team_ids,
    )


class Migration(migrations.Migration):
    # Each repair commits in its own transaction so locks are released as the scan
    # proceeds; the operation is a conditional data repair, safe to resume on failure.
    atomic = False

    dependencies = [
        ("conversations", "0090_pylon_issue_uniq"),
        ("posthog", "1393_revokedteamsecrettoken"),
    ]

    operations = [
        migrations.RunPython(reconcile_signing_secrets, migrations.RunPython.noop, elidable=True),
    ]
