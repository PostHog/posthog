from django.db import migrations


def disable_reports_for_disabled_evaluations(apps, schema_editor):
    # Backfill for the enabled-cascade added to the Evaluation post_save signal: reports attached to
    # an already-disabled (paused) evaluation predate the cascade and are still enabled, so they keep
    # emitting empty digests. Deleted evaluations are handled separately by 0007, so scope to
    # not-deleted evaluations here. The affected set is small (a few hundred rows), so a single
    # unbatched UPDATE holds locks only momentarily.
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    EvaluationReport = apps.get_model("ai_observability", "EvaluationReport")

    disabled_eval_ids = Evaluation.objects.filter(enabled=False, deleted=False).values_list("id", flat=True)
    EvaluationReport.objects.filter(
        evaluation_id__in=disabled_eval_ids,
        deleted=False,
        enabled=True,
    ).update(enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0028_drop_trial_eval_columns"),
    ]

    operations = [
        migrations.RunPython(
            disable_reports_for_disabled_evaluations,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
