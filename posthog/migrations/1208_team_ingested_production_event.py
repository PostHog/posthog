from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1207_migrate_ai_observability_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_production_event",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
