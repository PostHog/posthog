from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1238_ducklakebackfill_earliest_event_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="event_retention_months",
            field=models.PositiveSmallIntegerField(db_default=84, default=84),
        ),
    ]
