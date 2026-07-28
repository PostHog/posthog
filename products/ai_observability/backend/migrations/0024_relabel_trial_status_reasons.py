from django.db import migrations


def relabel_trial_status_reasons(apps, schema_editor):
    """Trial evaluations are gone, so any evaluation still carrying a trial-era disable reason is now
    just a keyless eval that needs a provider key. 0017 relabeled terminal teams but left mid-trial
    (grandfathered) teams' labels intact; sweep whatever remains to `provider_key_required`."""
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    Evaluation.objects.filter(status_reason__in=["trial_limit_reached", "model_not_allowed"]).update(
        status_reason="provider_key_required", status_reason_detail=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0023_llmpromptlabel"),
    ]

    operations = [
        # Lossy relabel; reverse is a no-op.
        migrations.RunPython(relabel_trial_status_reasons, migrations.RunPython.noop),
    ]
