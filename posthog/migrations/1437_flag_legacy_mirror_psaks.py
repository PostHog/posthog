from django.db import migrations

import structlog

from posthog.models.utils import hash_key_value

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def flag_mirror_rows(apps, schema_editor):
    """
    Mark every PSAK row whose hash equals a team's current legacy secret token (or backup)
    as a legacy mirror (#63111). The hash join is exact while the plaintext columns still
    exist; rows minted after this runs get the flag from create_project_secret_api_key_for_token.
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

    flagged_total = 0
    pending: list[str] = []
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        pending.append(hash_key_value(team.secret_api_token))
        if team.secret_api_token_backup:
            pending.append(hash_key_value(team.secret_api_token_backup))
        if len(pending) >= BATCH_SIZE:
            flagged_total += (
                ProjectSecretAPIKey.objects.using(db).filter(secure_value__in=pending).update(is_legacy_mirror=True)
            )
            pending = []
    if pending:
        flagged_total += (
            ProjectSecretAPIKey.objects.using(db).filter(secure_value__in=pending).update(is_legacy_mirror=True)
        )

    logger.info("flagged_legacy_mirror_psaks", flagged_rows=flagged_total)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1436_projectsecretapikey_is_legacy_mirror")]

    operations = [
        migrations.RunPython(flag_mirror_rows, migrations.RunPython.noop, elidable=True),
    ]
