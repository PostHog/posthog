from django.db import migrations


def disable_reports_for_disabled_evaluations(apps, schema_editor):
    # Backfill reports attached to evaluations that users explicitly paused. Error states also set
    # enabled=False, but must preserve the report preference so delivery can resume after recovery.
    # Deleted evaluations are handled separately by 0007.
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    EvaluationReport = apps.get_model("ai_observability", "EvaluationReport")

    paused_eval_ids = Evaluation.objects.filter(status="paused", deleted=False).values_list("id", flat=True)
    EvaluationReport.objects.filter(
        evaluation_id__in=paused_eval_ids,
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
