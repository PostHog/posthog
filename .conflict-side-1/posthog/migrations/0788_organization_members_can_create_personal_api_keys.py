from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0787_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="members_can_use_personal_api_keys",
            field=models.BooleanField(default=True),
        ),
    ]
