from django.db import migrations, models


def safety_backfill(apps, schema_editor):
    """Catch any rows missed by the initial backfill."""
    Experiment = apps.get_model("posthog", "Experiment")
    Experiment.objects.filter(status__isnull=True, start_date__isnull=True).update(status="draft")
    Experiment.objects.filter(status__isnull=True, start_date__isnull=False, end_date__isnull=True).update(
        status="running"
    )
    Experiment.objects.filter(status__isnull=True, end_date__isnull=False).update(status="stopped")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1037_experiment_status_backfill"),
    ]

    operations = [
        migrations.RunPython(safety_backfill, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="experiment",
            name="status",
            field=models.CharField(
                choices=[("draft", "Draft"), ("running", "Running"), ("stopped", "Stopped")],
                default="draft",
                max_length=20,
            ),
        ),
    ]
