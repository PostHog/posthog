from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0081_evaluation_backfill_max_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationreportrun",
            name="delivery_destinations",
            field=models.JSONField(db_default=[], default=list),
        ),
    ]
