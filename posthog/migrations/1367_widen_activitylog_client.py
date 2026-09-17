from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Widen `posthog_activitylog.client` so a server-derived client tag fits.

    A scout run's writes are tagged `scout:<skill_name>`, and a scout name alone can fill most
    of the 32 characters the column held, so the tag would be truncated mid-name.

    Postgres stores varchar(n) with the length as a catalog check, so raising n rewrites no rows.
    The ALTER still takes a brief ACCESS EXCLUSIVE lock on the table.
    """

    dependencies = [("posthog", "1366_project_deletion_scheduled_at")]

    operations = [
        migrations.AlterField(
            model_name="activitylog",
            name="client",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
