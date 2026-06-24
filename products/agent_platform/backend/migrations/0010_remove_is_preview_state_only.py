from django.db import migrations


class Migration(migrations.Migration):
    """Phase 1 of dropping `is_preview` from agent_session + agent_tool_approval_request.

    State-only: Django stops naming the column, the column stays in the DB. A
    follow-up PR — landed only after this deploy has fully rolled out — adds
    the matching `ALTER TABLE ... DROP COLUMN` migration. Splitting the phases
    across deploys is what lets a rolling deploy run new code against the old
    column without 5xx: old replicas still see a column they can safely INSERT
    into while the new code never names it; the column drop then runs after
    the last old replica is gone.
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
