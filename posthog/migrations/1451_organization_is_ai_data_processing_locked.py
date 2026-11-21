from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1450_organization_entitlement_applied_state")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="is_ai_data_processing_locked",
            field=models.BooleanField(
                blank=True,
                default=False,
                help_text="When True, AI data processing cannot be turned on through the UI or API, and members cannot ask admins to turn it on. Set at the organization's request.",
                null=True,
            ),
        ),
    ]
