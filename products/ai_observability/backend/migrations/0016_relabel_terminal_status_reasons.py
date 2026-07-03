from django.db import migrations, models


def backfill_terminal_status_reasons(apps, schema_editor):
    """Terminal teams — never started (used == 0, or no config row) or already exhausted the
    trial — should see evaluations as if trials never existed, so relabel their trial-flavored
    disable reasons to `provider_key_required`. Only mid-trial (grandfathered) teams keep their
    existing, still-accurate labels. The grandfathered set deliberately omits the deprecation
    cutoff: this runs at deploy time, before the cutoff; a self-hosted instance migrating after
    it just keeps a few stale-but-blocked labels."""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")

    grandfathered_team_ids = EvaluationConfig.objects.filter(
        trial_evals_used__gt=0, trial_evals_used__lt=models.F("trial_eval_limit")
    ).values_list("team_id", flat=True)

    Evaluation.objects.filter(
        status_reason__in=["trial_limit_reached", "model_not_allowed"],
    ).exclude(team_id__in=list(grandfathered_team_ids)).update(
        status_reason="provider_key_required", status_reason_detail=None
    )


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0015_deprecate_trial_evaluations")]

    operations = [
        # Lossy relabel (several trial reasons collapse into one); reverse is a no-op.
        migrations.RunPython(backfill_terminal_status_reasons, migrations.RunPython.noop),
    ]
