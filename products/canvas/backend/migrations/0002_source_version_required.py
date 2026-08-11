import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("canvas", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="canvasbuild",
            name="source_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="builds",
                to="canvas.canvassourceversion",
            ),
        )
    ]
