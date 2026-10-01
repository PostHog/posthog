import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1390_rename_desktop_canvas_comment_scope"),
        ("canvas", "0022_canvas_fork_lineage"),
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
