import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1360_validate_taggeditem_experiment_fk"),
        ("canvas", "0021_canvas_fork_lineage"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharingconfiguration",
            name="canvas",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="canvas.canvas",
            ),
        ),
    ]
