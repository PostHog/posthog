# Step 2 of 3: copy the application's ciphertext verbatim onto its non-archived
# revisions. Same Fernet key schedule + text format, so a raw column copy is
# lossless and doesn't depend on the encryption key being importable at migrate
# time.
#
# This runs as one UPDATE inside the default per-migration atomic transaction.
# At current scale (low hundreds of revisions) row locks held for the duration
# are not a concern. If `agent_revision` ever grows past ~10k rows, switch to
# `atomic = False` and a chunked loop (e.g. `UPDATE ... WHERE id IN (SELECT id
# ... LIMIT 1000 FOR UPDATE SKIP LOCKED)` driven by Python) so the migration
# doesn't hold a long-running transaction.

from django.db import migrations


def copy_env_to_revisions(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE agent_revision r
            SET encrypted_env = a.encrypted_env
            FROM agent_application a
            WHERE r.application_id = a.id
              AND a.encrypted_env IS NOT NULL
              AND r.state <> 'archived'
            """
        )


def noop(apps, schema_editor):
    # Reverse is a no-op: the application column is still present at this point
    # (0006 hasn't run yet), so the source of truth is intact and there's
    # nothing meaningful to clear on the revision side.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0004_agentrevision_encrypted_env"),
    ]

    operations = [
        migrations.RunPython(copy_env_to_revisions, noop),
    ]
