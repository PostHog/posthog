from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1127_alter_integration_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
