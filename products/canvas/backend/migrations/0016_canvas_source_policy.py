from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0015_remove_canvas_discussion_task_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvas",
            name="source_policy",
            field=models.CharField(db_default="standard", default="standard", max_length=32),
        ),
    ]
