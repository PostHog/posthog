"""No backfill: existing rows keep condition_type = NULL until they're next saved (or resaved
via the resave_cohorts management command), which the Rust realtime-membership gate treats as
"no behavioral condition" (safe default, falls back to legacy dynamic evaluation). Before
allowlisting a team in REALTIME_COHORT_EVALUATION_TEAM_IDS, run
`python manage.py resave_cohorts --team-id <id>` so its already-backfilled behavioral cohorts
get classified and keep using the realtime cohort_membership path."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0004_cohort_backfill_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="condition_type",
            field=models.JSONField(
                blank=True,
                help_text=(
                    "Flags describing which kinds of conditions the cohort's filters contain: "
                    "person_properties (property or person_metadata), behavioral, lifecycle "
                    "(first-seen/regularly/stopped/restarted performing an event), and cohorts "
                    "(nested cohort references). Null when the cohort has no filters to classify."
                ),
                null=True,
            ),
        ),
    ]
