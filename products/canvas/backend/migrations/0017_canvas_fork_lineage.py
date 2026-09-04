from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0016_canvas_source_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvas",
            name="forked_from_canvas_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="canvas",
            name="forked_from_version_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
