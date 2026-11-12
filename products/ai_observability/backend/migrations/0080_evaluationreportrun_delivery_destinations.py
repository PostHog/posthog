from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0079_move_default_report_cooldowns_to_daily"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationreportrun",
            name="delivery_destinations",
            field=models.JSONField(db_default=[], default=list),
        ),
    ]
