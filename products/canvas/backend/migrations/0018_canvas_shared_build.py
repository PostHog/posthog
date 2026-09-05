import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0017_canvas_fork_lineage"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvas",
            name="shared_build",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="canvas.canvasbuild",
            ),
        ),
    ]
