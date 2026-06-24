from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2: drop the `is_preview` columns from agent_session and
    agent_tool_approval_request.

    Stacked on top of `0010_remove_is_preview_state_only`. The two-phase
    split is what keeps a rolling deploy safe: 0010 ships first so Django
    stops naming the column while old replicas can still INSERT into it; this
    migration then runs only after the deploy has fully rolled out, so no
    in-flight code is still writing to the column when the DDL executes.

    `IF EXISTS` keeps the migration idempotent under `bin/migrate` retries.
    Reverse SQL re-adds the columns with `DEFAULT false NOT NULL` so a
    rollback isn't load-bearing on the column being absent.
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
