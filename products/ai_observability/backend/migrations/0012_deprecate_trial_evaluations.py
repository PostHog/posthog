from django.db import migrations, models


def backfill_terminal_status_reasons(apps, schema_editor):
    """Teams that already exhausted the trial are terminal, so their trial-flavored disable reasons
    should read as if trials never existed. Relabel them to `provider_key_required`. Mid-trial
    (grandfathered) teams keep their existing, still-accurate labels."""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")

    exhausted_team_ids = EvaluationConfig.objects.filter(
        trial_evals_used__gte=models.F("trial_eval_limit")
    ).values_list("team_id", flat=True)

    Evaluation.objects.filter(
        team_id__in=list(exhausted_team_ids),
        status_reason__in=["trial_limit_reached", "model_not_allowed"],
    ).update(status_reason="provider_key_required")


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0011_evaluation_target")]

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
        # Lossy relabel (several trial reasons collapse into one); reverse is a no-op.
        migrations.RunPython(backfill_terminal_status_reasons, migrations.RunPython.noop),
    ]
