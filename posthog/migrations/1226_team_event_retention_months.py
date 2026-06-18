from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1225_team_llm_gateway_overspend_allowance_usd"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="event_retention_months",
            field=models.PositiveSmallIntegerField(db_default=84, default=84),
        ),
    ]
