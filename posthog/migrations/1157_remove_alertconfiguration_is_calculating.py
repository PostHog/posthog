from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 1 of 2: Remove is_calculating from Django state.

    This keeps the column in the database but removes it from the Django model.
    The actual column drop happens in migration 1128.

    The field was used by the old Celery alert check flow to prevent two workers
    from running the same alert check concurrently. The Temporal-based flow
    introduced in the alerts->Temporal migration (PR1–PR3) relies on Temporal's
    deterministic workflow ID guarantee instead, so the flag is dead state.
    See docs/superpowers/specs/2026-04-08-alerts-temporal-migration-design.md.
    """

    dependencies = [
        ("posthog", "1156_cohort_team_filters_help_text"),
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
