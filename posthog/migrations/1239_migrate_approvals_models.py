from typing import Any

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1238_ducklakebackfill_earliest_event_date"),
    ]

    # State-only move: the approval models now live in the `approvals` app
    # (products/approvals/backend). No database_operations — the physical tables are
    # untouched and recreated in ORM state by products/approvals/backend/migrations/0001_initial.py.
    database_operations: list[Any] = []

    state_operations = [
        migrations.AlterUniqueTogether(
            name="approvalpolicy",
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name="approvalpolicy",
            name="bypass_roles",
        ),
        migrations.RemoveField(
            model_name="approvalpolicy",
            name="created_by",
        ),
        migrations.RemoveField(
            model_name="approvalpolicy",
            name="organization",
        ),
        migrations.RemoveField(
            model_name="approvalpolicy",
            name="team",
        ),
        migrations.RemoveField(
            model_name="changerequest",
            name="applied_by",
        ),
        migrations.RemoveField(
            model_name="changerequest",
            name="created_by",
        ),
        migrations.RemoveField(
            model_name="changerequest",
            name="organization",
        ),
        migrations.RemoveField(
            model_name="changerequest",
            name="team",
        ),
        migrations.DeleteModel(
            name="Approval",
        ),
        migrations.DeleteModel(
            name="ApprovalPolicy",
        ),
        migrations.DeleteModel(
            name="ChangeRequest",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(database_operations=database_operations, state_operations=state_operations)
    ]
