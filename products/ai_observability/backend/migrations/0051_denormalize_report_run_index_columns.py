from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0050_alter_evaluationreportrun_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationreportrun",
            name="title",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="evaluationreportrun",
            name="evaluation_target",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="evaluationreportrun",
            name="generation_status",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
