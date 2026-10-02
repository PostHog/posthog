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


def _flush(ProjectSecretAPIKey, db, pending: list[dict]) -> int:
    """Insert one chunk with three queries, so row locks last seconds overall instead
    of one round trip per token."""
    existing = set(
        ProjectSecretAPIKey.objects.using(db)
        .filter(secure_value__in=[p["secure_value"] for p in pending])
        .values_list("secure_value", flat=True)
    )
    # A customer may already use these exact labels; (team, label) is unique.
    candidate_labels = {p["label"] for p in pending} | {f"{p['label']} {p['secure_value'][-8:]}" for p in pending}
    taken = set(
        ProjectSecretAPIKey.objects.using(db)
        .filter(team_id__in={p["team_id"] for p in pending}, label__in=candidate_labels)
        .values_list("team_id", "label")
    )
    rows = []
    for p in pending:
        if p["secure_value"] in existing:
            continue
        existing.add(p["secure_value"])
        label = p["label"]
        if (p["team_id"], label) in taken:
            label = f"{label} {p['secure_value'][-8:]}"
            if (p["team_id"], label) in taken:
                # Both labels taken: skip rather than abort the deploy; the pre-drop
                # sweep (#66179) retries and the legacy token keeps working meanwhile.
                logger.warning("backfill_label_collision_skipped", team_id=p["team_id"])
                continue
        taken.add((p["team_id"], label))
        rows.append(
            ProjectSecretAPIKey(
                team_id=p["team_id"],
                label=label,
                secure_value=p["secure_value"],
                mask_value=p["mask_value"],
                scopes=MIGRATED_SCOPES,
            )
        )
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
    pending: list[dict] = []
    for team in teams.iterator(chunk_size=BATCH_SIZE):
        tokens = [(team.secret_api_token, "Migrated legacy secret API key")]
        if team.secret_api_token_backup:
            tokens.append((team.secret_api_token_backup, "Migrated legacy key (backup)"))
        for token, label in tokens:
            pending.append(
                {
                    "team_id": team.id,
                    "secure_value": hash_key_value(token),
                    "mask_value": mask_key_value(token),
                    "label": label,
                }
            )
        if len(pending) >= BATCH_SIZE:
            created_total += _flush(ProjectSecretAPIKey, db, pending)
            pending = []
    if pending:
        created_total += _flush(ProjectSecretAPIKey, db, pending)

    logger.info("backfilled_secret_tokens_to_psak", created_rows=created_total)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1391_organization_provisioning"),
    ]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop, elidable=True),
    ]
