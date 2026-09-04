import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1334_sharingconfiguration_canvas"),
        ("tasks", "0115_sharedtaskartifact"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharingconfiguration",
            name="task_artifact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sharing_configurations",
                to="tasks.sharedtaskartifact",
            ),
        ),
    ]
