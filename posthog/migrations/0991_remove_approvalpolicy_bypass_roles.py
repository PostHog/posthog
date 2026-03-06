from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 1 of 2: Remove bypass_roles from Django state.

    This keeps the column in the database but removes it from the Django model.
    The actual column drop happens in migration 0992.

    Feature was never deployed, so this is safe.
    """

    dependencies = [
        ("posthog", "0990_projectsecretapikey"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="bypass_roles",
                ),
            ],
            database_operations=[],
        ),
    ]
