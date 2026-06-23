from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1233_backfill_duckgresserverteam"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="post_all_insights_in_main_message",
            field=models.BooleanField(default=False),
        ),
    ]
