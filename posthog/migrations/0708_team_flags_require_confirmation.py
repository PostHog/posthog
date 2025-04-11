from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0707_file_system_shortcut"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="flags_require_confirmation",
            field=models.BooleanField(default=False),
        ),
    ]
