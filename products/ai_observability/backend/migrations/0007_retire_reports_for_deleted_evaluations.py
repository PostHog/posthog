from django.db import migrations


def retire_reports_for_deleted_evaluations(apps, schema_editor):
    # Safe to run synchronously and unbatched: at PR time the affected set was tiny —
    # 180 orphaned rows of 936 total (US) and 69 of 361 (EU), 249 rows across 88 teams.
    # A single UPDATE over a few hundred rows holds locks only momentarily.
    EvaluationReport = apps.get_model("ai_observability", "EvaluationReport")
    EvaluationReport.objects.filter(evaluation__deleted=True, deleted=False).update(deleted=True, enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0006_alter_evaluation_evaluation_type_and_more"),
    ]

    operations = [
        migrations.RunPython(
            retire_reports_for_deleted_evaluations,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
