from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1243_alter_team_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="event_retention_months",
            field=models.PositiveSmallIntegerField(db_default=84, default=84),
        ),
    ]
