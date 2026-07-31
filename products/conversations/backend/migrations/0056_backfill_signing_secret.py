from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def backfill_signing_secrets(apps, schema_editor):
    """
    Copy Team.secret_api_token into the conversations SigningSecret table (#63111)
    so widget identity verification can move off the plaintext column with zero
    customer impact. Rows created after this runs are kept in sync by the
    secret_api_token_rotated signal.
    """
    Team = apps.get_model("posthog", "Team")
    SigningSecret = apps.get_model("conversations", "SigningSecret")

    # Idempotent under bin/migrate retries: skip teams that already have a row.
    existing_team_ids = set(SigningSecret.objects.values_list("team_id", flat=True))

    teams = (
        Team.objects.exclude(secret_api_token__isnull=True).exclude(secret_api_token="").only("id", "secret_api_token")
    )

    total = 0
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        if team.id in existing_team_ids:
            continue
        # Per-row save() so EncryptedTextField encrypts through the ORM field layer;
        # a raw SQL copy would store the value as plaintext.
        SigningSecret(team_id=team.id, secret=team.secret_api_token).save()
        total += 1

    logger.info("backfilled_conversations_signing_secrets", created_rows=total)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0055_signingsecret"),
    ]

    operations = [
        migrations.RunPython(backfill_signing_secrets, migrations.RunPython.noop, elidable=True),
    ]
