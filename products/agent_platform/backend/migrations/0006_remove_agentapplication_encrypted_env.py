# Step 3 of 3: remove `encrypted_env` from `agent_application` in Django state
# only — the column stays in the DB.
#
# A bare `RemoveField` would `DROP COLUMN` immediately, which (a) can't be
# rolled back if the deploy is reverted and (b) breaks any in-flight web/worker
# process still running the old code. The migration risk analyzer blocks
# unstaged column drops for that reason.
#
# Multi-phase pattern (see safe-django-migrations.md `#dropping-columns`):
#   1. This migration: drop the field from Django state; column persists.
#   2. Deploy and let one full deploy cycle pass — old code with the field is
#      retired, every reader has moved to the revision-level column.
#   3. Follow-up migration: `RunSQL("ALTER TABLE agent_application DROP COLUMN
#      IF EXISTS encrypted_env")` — the analyzer recognizes this as a properly
#      staged drop because of the state removal here.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0005_copy_encrypted_env_to_revisions"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="agentapplication",
                    name="encrypted_env",
                ),
            ],
            database_operations=[],
        ),
    ]
