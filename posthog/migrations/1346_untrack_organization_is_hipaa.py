from django.db import migrations


class Migration(migrations.Migration):
    """Take `is_hipaa` out of Django's model state only.

    The AI training lock now reads whether the organization has a signed BAA, so nothing
    reads this column any more. The column stays in Postgres so a rollback to the previous
    release still works, and so in-flight requests on old code keep finding it. A later
    migration drops it for real - see safe-django-migrations.md "Dropping Columns".
    """

    dependencies = [
        ("posthog", "1345_squash_2026_09_07_schema_addons"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="organization",
                    name="is_hipaa",
                ),
            ],
            database_operations=[],
        ),
    ]
