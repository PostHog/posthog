from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0047_add_customer_task_foreign_keys"),
    ]

    operations = [
        ValidateForeignKey(model_name="customertask", name="ca_customer_task_team_id_fk"),
        ValidateForeignKey(model_name="customertask", name="ca_customer_task_assigned_to_id_fk"),
        ValidateForeignKey(model_name="customertask", name="ca_customer_task_completed_by_id_fk"),
        ValidateForeignKey(model_name="customertask", name="ca_customer_task_created_by_id_fk"),
        ValidateForeignKey(model_name="customertaskactivity", name="ca_customer_task_activity_team_id_fk"),
        ValidateForeignKey(model_name="customertaskactivity", name="ca_customer_task_activity_actor_id_fk"),
    ]
