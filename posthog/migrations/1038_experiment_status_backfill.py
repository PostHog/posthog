from django.db import migrations
from django.db.models import Case, Value, When


def backfill_experiment_status(apps, schema_editor):
    Experiment = apps.get_model("posthog", "Experiment")

    Experiment.objects.filter(status__isnull=True).update(
        status=Case(
            When(start_date__isnull=True, then=Value("draft")),
            When(start_date__isnull=False, end_date__isnull=True, then=Value("running")),
            When(start_date__isnull=False, end_date__isnull=False, then=Value("stopped")),
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1037_add_redirect_to_topic_restriction_type"),
    ]

    operations = [
        migrations.RunPython(backfill_experiment_status, reverse_code=migrations.RunPython.noop),
    ]
