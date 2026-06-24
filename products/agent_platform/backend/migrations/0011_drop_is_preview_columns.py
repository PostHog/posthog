from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2: drop the `is_preview` columns from agent_session and
    agent_tool_approval_request. Django state already lost the field in 0010,
    so this is a pure DDL drop. `IF EXISTS` keeps the migration idempotent
    under `bin/migrate` retries.
    """

    dependencies = [
        ("agent_platform", "0010_remove_is_preview_state_only"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE agent_session DROP COLUMN IF EXISTS is_preview;",
            reverse_sql="ALTER TABLE agent_session ADD COLUMN IF NOT EXISTS is_preview boolean NOT NULL DEFAULT false;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE agent_tool_approval_request DROP COLUMN IF EXISTS is_preview;",
            reverse_sql="ALTER TABLE agent_tool_approval_request ADD COLUMN IF NOT EXISTS is_preview boolean NOT NULL DEFAULT false;",
        ),
    ]
