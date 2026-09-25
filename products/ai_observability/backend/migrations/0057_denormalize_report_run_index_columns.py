from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0056_alter_evaluationbackfill_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationreportrun",
            name="title",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="evaluationreportrun",
            name="evaluation_target",
            field=models.CharField(blank=True, db_default="", default="", max_length=32),
        ),
        migrations.AddField(
            model_name="evaluationreportrun",
            name="generation_status",
            field=models.CharField(blank=True, db_default="", default="", max_length=32),
        ),
    ]
