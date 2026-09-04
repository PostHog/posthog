import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1340_sharingconfiguration_canvas"),
        ("tasks", "0117_sharedtaskartifact"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharingconfiguration",
            name="task_artifact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="tasks.sharedtaskartifact",
            ),
        ),
    ]
