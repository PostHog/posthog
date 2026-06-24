from django.db import migrations


class Migration(migrations.Migration):
    """Phase 1 of dropping `is_preview` from agent_session + agent_tool_approval_request.

    State-only: Django stops naming the column, the column stays in the DB.
    `0011_drop_is_preview_columns` then issues `ALTER TABLE ... DROP COLUMN`.
    Splitting these lets a rolling deploy run new code against the old column
    without 5xx — old replicas still see a column they can safely INSERT into;
    new code never names it.
    """

    dependencies = [
        ("agent_platform", "0009_agentsession_agenttoolapprovalrequest_is_preview"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="agentsession", name="is_preview"),
                migrations.RemoveField(model_name="agenttoolapprovalrequest", name="is_preview"),
            ],
            database_operations=[],
        ),
    ]
