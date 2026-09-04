import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1341_organization_uses_most_specific_access_resolution"),
        ("canvas", "0016_canvas_source_policy"),
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
