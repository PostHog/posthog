from django.db import migrations


def resweep_trial_status_reasons(apps, schema_editor):
    """0024 relabeled trial-era status reasons, but workers on the previous release could still
    write `trial_limit_reached` / `model_not_allowed` during the rollout after that sweep ran.
    No writer of these values exists anymore, so this second sweep is final."""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    Evaluation.objects.filter(status_reason__in=["trial_limit_reached", "model_not_allowed"]).update(
        status_reason="provider_key_required", status_reason_detail=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0026_retire_trial_columns"),
    ]

    operations = [
        # Lossy relabel; reverse is a no-op.
        migrations.RunPython(resweep_trial_status_reasons, migrations.RunPython.noop),
    ]
