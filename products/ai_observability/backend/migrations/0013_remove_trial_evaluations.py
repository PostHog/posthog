from django.db import migrations, models


def backfill_remaining_trial_status_reasons(apps, schema_editor):
    """Trial evaluations are gone: any evaluation still disabled for a trial-era reason is now simply
    a keyless eval that needs a provider key. Relabel the remainder to `provider_key_required`.
    (Migration 0012 already relabeled exhausted teams; this sweeps whatever is left.)"""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    Evaluation.objects.filter(status_reason__in=["trial_limit_reached", "model_not_allowed"]).update(
        status_reason="provider_key_required"
    )


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0012_deprecate_trial_evaluations")]

    operations = [
        # Lossy relabel; reverse is a no-op.
        migrations.RunPython(backfill_remaining_trial_status_reasons, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="evaluation",
            name="status_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("provider_key_required", "No provider API key configured"),
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
        migrations.RemoveField(model_name="evaluationconfig", name="trial_eval_limit"),
        migrations.RemoveField(model_name="evaluationconfig", name="trial_evals_used"),
    ]
