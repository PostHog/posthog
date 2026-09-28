from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0059_customertask_assigned_to_agent"),
    ]

    operations = [
        ValidateConstraint(model_name="customertask", name="customer_task_agent_assignee_exclusive"),
    ]
