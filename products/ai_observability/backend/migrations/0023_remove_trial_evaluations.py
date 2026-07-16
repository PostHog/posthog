from django.db import migrations, models


def backfill_remaining_trial_status_reasons(apps, schema_editor):
    """Trial evaluations are gone, so any evaluation still carrying a trial-era disable reason is now
    just a keyless eval that needs a provider key. 0017 relabeled terminal teams but left mid-trial
    (grandfathered) teams' labels intact; sweep whatever remains to `provider_key_required`."""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    Evaluation.objects.filter(status_reason__in=["trial_limit_reached", "model_not_allowed"]).update(
        status_reason="provider_key_required", status_reason_detail=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0022_add_generated_delivery_status"),
    ]

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
        # Retire the trial columns from Django's state now, but keep the columns in the DB so pods
        # still running the previous release keep working through the rollout. Drop NOT NULL so the
        # new code (which no longer writes these) can insert config rows without them. A follow-up
        # migration physically drops the columns once the previous release is fully gone.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit DROP NOT NULL;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used DROP NOT NULL;",
                    ],
                    reverse_sql=[
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_evals_used SET NOT NULL;",
                        "ALTER TABLE llm_analytics_evaluationconfig ALTER COLUMN trial_eval_limit SET NOT NULL;",
                    ],
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="evaluationconfig", name="trial_eval_limit"),
                migrations.RemoveField(model_name="evaluationconfig", name="trial_evals_used"),
            ],
        ),
    ]
