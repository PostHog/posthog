from django.db import migrations


class Migration(migrations.Migration):
    """The platform's models leave this app's state. The tables stay where they are.

    `alerts_platform.0001_initial` recreates them in the new app's state under the same
    `db_table`, so no table is created, dropped or renamed by either migration.
    """

    dependencies = [
        ("alerts", "0011_platformalertthread"),
        ("alerts_platform", "0001_initial"),
    ]

    database_operations: list = []

    state_operations = [
        migrations.DeleteModel("PlatformAlertThread"),
        migrations.DeleteModel("PlatformAlert"),
        migrations.DeleteModel("PlatformAlertConfiguration"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(database_operations=database_operations, state_operations=state_operations)
    ]
