from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [("customer_analytics", "0047_customertask_customertaskactivity_and_more")]

    operations = [
        AddForeignKeyNotValid(
            model_name="customertask",
            name="ca_customer_task_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="customertask",
            name="ca_customer_task_assigned_to_id_fk",
            column="assigned_to_id",
            to_table="posthog_user",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="customertask",
            name="ca_customer_task_completed_by_id_fk",
            column="completed_by_id",
            to_table="posthog_user",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="customertask",
            name="ca_customer_task_created_by_id_fk",
            column="created_by_id",
            to_table="posthog_user",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="customertaskactivity",
            name="ca_customer_task_activity_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="customertaskactivity",
            name="ca_customer_task_activity_actor_id_fk",
            column="actor_id",
            to_table="posthog_user",
            to_column="id",
        ),
    ]
