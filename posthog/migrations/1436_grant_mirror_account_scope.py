from django.db import migrations
from django.db.models import F, Func, Value

import structlog

from posthog.models.utils import hash_key_value

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

# Keep in sync with MIRRORED_LEGACY_TOKEN_ACCOUNT_SCOPE; migrations must not import app code.
ACCOUNT_SCOPE = "legacy_account:write"


def _flush(ProjectSecretAPIKey, db, hashes: list[str]) -> int:
    return (
        ProjectSecretAPIKey.objects.using(db)
        .filter(secure_value__in=hashes)
        .exclude(scopes__contains=[ACCOUNT_SCOPE])
        .update(scopes=Func(F("scopes"), Value(ACCOUNT_SCOPE), function="array_append"))
    )


def grant_mirror_account_scope(apps, schema_editor):
    """
    Append the internal legacy_account:write scope to every PSAK row whose hash equals a
    team's current legacy secret token (or backup), so those tokens keep their customer
    analytics single-account access when the legacy verifiers go away (#66179). The hash
    join is exact while the plaintext columns still exist; rows minted later get the scope
    from create_project_secret_api_key_for_token.
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

    granted_total = 0
    pending: list[str] = []
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        pending.append(hash_key_value(team.secret_api_token))
        if team.secret_api_token_backup:
            pending.append(hash_key_value(team.secret_api_token_backup))
        if len(pending) >= BATCH_SIZE:
            granted_total += _flush(ProjectSecretAPIKey, db, pending)
            pending = []
    if pending:
        granted_total += _flush(ProjectSecretAPIKey, db, pending)

    logger.info("granted_mirror_account_scope", granted_rows=granted_total)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1435_ema_issuer_management")]

    operations = [
        migrations.RunPython(grant_mirror_account_scope, migrations.RunPython.noop, elidable=True),
    ]
