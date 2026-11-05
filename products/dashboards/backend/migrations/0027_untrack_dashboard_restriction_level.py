from django.db import migrations, models

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0026_dashboardtile_group_key_badge"),
    ]

    operations = [
        # New pods stop naming the column in INSERTs once it leaves model state, so the column
        # needs a database default for the rolling deploy. Without it Postgres stores NULL, and a
        # previous-release pod still runs `dashboard.restriction_level > EVERYONE_IN_PROJECT_CAN_EDIT`,
        # which raises TypeError on None and cannot return the dashboard at all.
        migrations.AlterField(
            model_name="dashboard",
            name="restriction_level",
            field=models.PositiveSmallIntegerField(null=True, db_default=21),
        ),
        untrack_field("dashboard", "restriction_level"),
    ]
