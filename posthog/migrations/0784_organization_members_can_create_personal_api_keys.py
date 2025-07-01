from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0783_remove_segment_engage_destinations"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="members_can_create_personal_api_keys",
            field=models.BooleanField(default=True, null=True, blank=True),
        ),
    ]
