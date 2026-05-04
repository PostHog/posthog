from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1138_onboarding_delegated_to_invite_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
