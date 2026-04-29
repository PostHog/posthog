from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1131_exportedasset_is_system"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
