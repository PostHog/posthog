from django.db import migrations, models

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0026_dashboardtile_group_key_badge"),
    ]

    operations = [
        # The column is NOT NULL with no database default, so it has to become nullable before
        # Django stops naming it in INSERTs. The RemoveField is state-only: the column and its
        # data stay for the deploy that still reads them.
        migrations.AlterField(
            model_name="dashboard",
            name="restriction_level",
            field=models.PositiveSmallIntegerField(null=True),
        ),
        untrack_field("dashboard", "restriction_level"),
    ]
