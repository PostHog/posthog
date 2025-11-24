from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add index to speed up CohortViewSet.get_queryset() subquery that fetches
    the most recent error_code per cohort. Without this index, each subquery
    requires an in-memory sort (~0.9ms per cohort). With ~500 cohorts, that
    adds ~450ms to the cohort list API response.
    """

    atomic = False

    dependencies = [
        ("posthog", "0921_cohortcalculationhistory_error_code"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="cohortcalculationhistory",
            index=models.Index(
                fields=["cohort", "-started_at"],
                name="cohort_calc_cohort_started_idx",
            ),
        ),
    ]
