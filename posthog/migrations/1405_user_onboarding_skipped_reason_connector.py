from django.db import migrations, models


class Migration(migrations.Migration):
    # choices live only in Django's state, so the database is left alone. A plain AlterField would
    # emit no SQL either, but it reads as a lock on posthog_user, which is read on every request.

    dependencies = [
        ("posthog", "1404_organization_inactive_quota_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="user",
                    name="onboarding_skipped_reason",
                    field=models.CharField(
                        blank=True,
                        choices=[
                            ("delegated", "Delegated to teammate"),
                            ("later", "Skipped for later"),
                            ("other", "Other"),
                            ("provisioned", "Account provisioned by a partner"),
                            ("connector", "Signed up through an OAuth connector"),
                        ],
                        max_length=32,
                        null=True,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
