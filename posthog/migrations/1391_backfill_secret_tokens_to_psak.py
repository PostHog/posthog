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


def backfill_tokens(apps, schema_editor):
    """
    Create a ProjectSecretAPIKey row holding the SHA256 of every existing legacy
    secret_api_token (and backup), so the same string keeps authenticating after the
    plaintext columns drop (#63111). Customers change nothing.
    """
    Team = apps.get_model("posthog", "Team")
    ProjectSecretAPIKey = apps.get_model("posthog", "ProjectSecretAPIKey")
    # Production applies migrations on a dedicated alias; unpinned managers would write
    # to "default", outside this migration's transaction.
    db = schema_editor.connection.alias

    teams = (
        Team.objects.using(db)
        .exclude(secret_api_token__isnull=True)
        .exclude(secret_api_token="")
        .only("id", "secret_api_token", "secret_api_token_backup")
    )

    created_total = 0
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        tokens = [(team.secret_api_token, "Migrated legacy secret API key")]
        if team.secret_api_token_backup:
            tokens.append((team.secret_api_token_backup, "Migrated legacy key (backup)"))
        for token, label in tokens:
            secure_value = hash_key_value(token)
            if ProjectSecretAPIKey.objects.using(db).filter(secure_value=secure_value).exists():
                continue
            # A customer may already use this exact label; (team, label) is unique.
            if ProjectSecretAPIKey.objects.using(db).filter(team_id=team.id, label=label).exists():
                label = f"{label[:31]} {secure_value[:8]}"
            ProjectSecretAPIKey.objects.using(db).create(
                team_id=team.id,
                label=label,
                secure_value=secure_value,
                mask_value=mask_key_value(token),
                scopes=MIGRATED_SCOPES,
            )
            created_total += 1

    logger.info("backfilled_secret_tokens_to_psak", created_rows=created_total)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1390_rename_desktop_canvas_comment_scope"),
    ]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop, elidable=True),
    ]
