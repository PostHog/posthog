from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1129_userintegration"),
    ]

    operations = [
        migrations.AddField(
            model_name="filesystemshortcut",
            name="order",
            field=models.IntegerField(default=0),
        ),
    ]
