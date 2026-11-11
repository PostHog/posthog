from django.db import migrations

import structlog

from posthog.models.utils import hash_key_value, mask_key_value

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

# The surfaces that keep accepting PSAKs after the legacy verifiers go away. Much
# narrower than the legacy token, which authorized every surface at once. account:read
# is deliberately absent: it would also open the customer-analytics bulk account export,
# which refuses the team-wide legacy token on purpose.
MIGRATED_SCOPES = ["feature_flag:read", "support_ticket:read"]


def _fallback_label(label: str, secure_value: str) -> str:
    return f"{label} {secure_value[-8:]}"


def _flush(ProjectSecretAPIKey, RevokedTeamSecretToken, db, pending: list) -> int:
    """Insert one chunk with four queries, so row locks last seconds overall instead
    of one round trip per token."""
    hashes = [key.secure_value for key in pending]
    existing = set(
        ProjectSecretAPIKey.objects.using(db).filter(secure_value__in=hashes).values_list("secure_value", flat=True)
    )
    # Read per chunk, not once up front: a mirror row deleted by leak revocation must
    # stay dead, including revocations that commit while this migration runs.
    existing |= set(
        RevokedTeamSecretToken.objects.using(db).filter(secure_value__in=hashes).values_list("secure_value", flat=True)
    )
    # A customer may already use these exact labels; (team, label) is unique.
    candidate_labels = {key.label for key in pending} | {
        _fallback_label(key.label, key.secure_value) for key in pending
    }
    taken = set(
        ProjectSecretAPIKey.objects.using(db)
        .filter(team_id__in={key.team_id for key in pending}, label__in=candidate_labels)
        .values_list("team_id", "label")
    )
    rows = []
    for key in pending:
        if key.secure_value in existing:
            continue
        existing.add(key.secure_value)
        if (key.team_id, key.label) in taken:
            key.label = _fallback_label(key.label, key.secure_value)
            if (key.team_id, key.label) in taken:
                # Both labels are taken, so skip this token rather than abort the deploy.
                # The legacy token keeps working. #66179 plans a second run of this
                # backfill before it drops the plaintext columns; that run retries this team.
                logger.warning("backfill_label_collision_skipped", team_id=key.team_id)
                continue
        taken.add((key.team_id, key.label))
        rows.append(key)
    ProjectSecretAPIKey.objects.using(db).bulk_create(rows)
    return len(rows)


def backfill_tokens(apps, schema_editor):
    """
    Create a ProjectSecretAPIKey row holding the SHA256 of every existing legacy
    secret_api_token (and backup), so the same string keeps authenticating after the
    plaintext columns drop (#63111). Customers change nothing.
    """
    Team = apps.get_model("posthog", "Team")
    ProjectSecretAPIKey = apps.get_model("posthog", "ProjectSecretAPIKey")
    RevokedTeamSecretToken = apps.get_model("posthog", "RevokedTeamSecretToken")
    # Production applies migrations on a dedicated alias; unpinned managers would write
    # to "default", outside this migration's transaction.
    db = schema_editor.connection.alias

    teams = (
        Team.objects.using(db)
        # Blocks a concurrent rotation from retiring a token between our read and our
        # insert (its UPDATE needs this lock), while no_key keeps FK writers unblocked.
        .select_for_update(no_key=True)
        .exclude(secret_api_token__isnull=True)
        .exclude(secret_api_token="")
        .only("id", "secret_api_token", "secret_api_token_backup")
    )

    created_total = 0
    pending: list = []
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        tokens = [(team.secret_api_token, "Migrated legacy secret API key")]
        if team.secret_api_token_backup:
            tokens.append((team.secret_api_token_backup, "Migrated legacy key (backup)"))
        for token, label in tokens:
            pending.append(
                ProjectSecretAPIKey(
                    team_id=team.id,
                    label=label,
                    secure_value=hash_key_value(token),
                    mask_value=mask_key_value(token),
                    scopes=MIGRATED_SCOPES,
                )
            )
        if len(pending) >= BATCH_SIZE:
            created_total += _flush(ProjectSecretAPIKey, RevokedTeamSecretToken, db, pending)
            pending = []
    if pending:
        created_total += _flush(ProjectSecretAPIKey, RevokedTeamSecretToken, db, pending)

    logger.info("backfilled_secret_tokens_to_psak", created_rows=created_total)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1393_revokedteamsecrettoken")]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop, elidable=True),
    ]
