from django.db import migrations


def backfill_experiment_status(apps, schema_editor):
    Experiment = apps.get_model("posthog", "Experiment")

    Experiment.objects.filter(status__isnull=True, start_date__isnull=True).update(status="draft")
    Experiment.objects.filter(status__isnull=True, start_date__isnull=False, end_date__isnull=True).update(
        status="running"
    )
    Experiment.objects.filter(status__isnull=True, start_date__isnull=False, end_date__isnull=False).update(
        status="stopped"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1037_add_redirect_to_topic_restriction_type"),
    ]

    operations = [
        migrations.RunPython(backfill_experiment_status, reverse_code=migrations.RunPython.noop),
    ]
