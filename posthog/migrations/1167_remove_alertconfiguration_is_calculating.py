from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 1 of 2: Remove is_calculating from Django state.

    This keeps the column in the database but removes it from the Django model.
    The actual column drop happens in the follow-up
    ``drop_alertconfiguration_is_calculating_column`` migration.

    The field was used by the old Celery alert check flow to prevent two workers
    from running the same alert check concurrently. The Temporal-based flow relies
    on Temporal's deterministic workflow ID guarantee instead, so the flag is dead
    state.
    """

    dependencies = [
        ("posthog", "1166_oauth_impersonated_by"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="alertconfiguration",
                    name="is_calculating",
                ),
            ],
            database_operations=[],
        ),
    ]
