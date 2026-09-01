from django.db import migrations


class Migration(migrations.Migration):
    """Take `reason` / `reason_text` out of Django's model state only.

    The columns stay in Postgres so a rollback to the previous release still works, and
    so in-flight requests on old code keep writing to columns that still exist. A later
    migration drops them for real - see safe-django-migrations.md "Dropping Columns".
    """

    dependencies = [
        ("posthog", "1327_untrack_cimd_metadata_url"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="userproductlist",
                    name="reason",
                ),
                migrations.RemoveField(
                    model_name="userproductlist",
                    name="reason_text",
                ),
            ],
            database_operations=[],
        ),
    ]
