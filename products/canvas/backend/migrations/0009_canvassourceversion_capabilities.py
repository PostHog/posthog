from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0008_remove_home_canvas"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvassourceversion",
            name="capabilities",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
