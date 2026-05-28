from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autoresearch", "0003_remove_autoresearchpipeline_prediction_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="autoresearchpipeline",
            name="training_lookback_days",
            field=models.IntegerField(
                default=180,
                help_text=(
                    "How far back to look for training examples. "
                    "Larger windows give more data but may include stale behavior."
                ),
            ),
        ),
    ]
