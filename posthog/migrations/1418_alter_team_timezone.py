from django.db import migrations, models

import posthog.models.team.team


class Migration(migrations.Migration):
    # choices lives only in Django's state, so the database is left alone. A plain AlterField would
    # emit no SQL either, but it reads as a lock on posthog_team, which is read on every request.

    dependencies = [
        ("posthog", "1417_organizationinvite_email_suppressed"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="team",
                    name="timezone",
                    field=models.CharField(
                        choices=posthog.models.team.team.timezone_choices,
                        default="UTC",
                        max_length=240,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
