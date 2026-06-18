# Move secrets from the application to the revision.
#
# `encrypted_env` used to live on `agent_application` (one shared secret bag for
# the live revision and every draft). It now lives on `agent_revision` so a
# draft can be previewed with its own secret values without touching the live
# revision's, and a promote carries the secrets it was tested with. This also
# removes the need for the per-session `preview_secret_override` overlay, which
# is dropped here (it was only ever added on this same feature branch — there is
# no released state carrying it).
#
# Steps: add the new column, copy the application's ciphertext verbatim onto its
# non-archived revisions (same Fernet key schedule + text format, so a raw
# column copy is lossless and doesn't depend on the encryption key being
# importable at migrate time), then drop the application column.

from django.db import migrations

import posthog.helpers.encrypted_fields


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
    # Reverse drops the revision column (handled by RemoveField's auto-reverse);
    # there's nothing meaningful to restore onto the re-added application column.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0004_agentsession_agenttoolapprovalrequest_is_preview"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrevision",
            name="encrypted_env",
            field=posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, null=True),
        ),
        migrations.RunPython(copy_env_to_revisions, noop),
        migrations.RemoveField(
            model_name="agentapplication",
            name="encrypted_env",
        ),
    ]
