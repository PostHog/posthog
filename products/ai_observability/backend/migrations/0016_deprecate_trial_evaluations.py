from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0015_llmprompt_version_description")]

    operations = [
        migrations.AlterField(
            model_name="evaluation",
            name="status_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("provider_key_required", "No provider API key configured"),
                    ("trial_limit_reached", "Trial evaluation limit reached"),
                    ("model_not_allowed", "Model not available on the trial plan"),
                    ("provider_key_deleted", "Provider API key was deleted"),
                    (
                        "no_default_model",
                        "No default model available for the selected provider",
                    ),
                    ("provider_key_invalid", "Provider API key is invalid"),
                    (
                        "provider_key_permission_denied",
                        "Provider API key lacks model access",
                    ),
                    ("provider_key_quota_exceeded", "Provider API key quota exceeded"),
                    ("provider_key_rate_limited", "Provider API key is rate limited"),
                    ("model_not_found", "Model not found"),
                    ("hog_error", "Hog evaluation code failed"),
                ],
                max_length=50,
                null=True,
            ),
        ),
    ]
