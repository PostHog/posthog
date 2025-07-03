from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0784_fix_null_event_triggers"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="members_can_use_personal_api_keys",
            field=models.BooleanField(default=True),
        ),
    ]
