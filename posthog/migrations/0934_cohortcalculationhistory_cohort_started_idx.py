from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add index to speed up retrieval of the most recent calculation result per cohort.
    Without this index, each subquery requires an in-memory sort (~0.9ms per cohort).
    With ~500 cohorts, that adds ~450ms to the cohort list API response.
    """

    atomic = False

    dependencies = [
        ("posthog", "0933_add_event_names_and_uuids_to_restriction_config"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="cohortcalculationhistory",
            index=models.Index(
                fields=["cohort", "-started_at"],
                name="posthog_coh_cohort__cbac1b_idx",
            ),
        ),
    ]
