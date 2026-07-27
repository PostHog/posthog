# Step 1 of 3: add the new column on the revision.
#
# `encrypted_env` is moving from `agent_application` (one shared secret bag for
# the live revision and every draft) to `agent_revision` so a draft can be
# previewed with its own secret values without touching the live revision's,
# and a promote carries the secrets it was tested with.
#
# This is split across three migrations so the data copy runs in its own step
# (the analyzer blocks RunPython combined with schema changes — schema locks
# during data migrations are how prod outages happen):
#   0004 add agent_revision.encrypted_env
#   0005 copy agent_application.encrypted_env onto its non-archived revisions
#   0006 drop agent_application.encrypted_env

from django.db import migrations

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0003_agentapplication_global_slug_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrevision",
            name="encrypted_env",
            field=posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, null=True),
        ),
    ]
