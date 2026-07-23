from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("autoresearch", "0002_autoresearchsuggestion_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="autoresearchpipeline",
            name="prediction_mode",
        ),
    ]
