from django.db import migrations, models


class Migration(migrations.Migration):
    # choices live only in Django's state, so the database is left alone. A plain AlterField would
    # emit no SQL either, but it reads as a lock on posthog_user, which is read on every request.

    dependencies = [
        ("posthog", "1431_squash_2026_11_02_schema_addons"),
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
                            ("device_login", "Signed up through an OAuth device login"),
                        ],
                        max_length=32,
                        null=True,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
