# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0992_drop_approvalpolicy_bypass_roles_column"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="requested_2fa_reset_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
