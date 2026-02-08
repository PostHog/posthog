from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0936_survey_headline_response_count_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_cohortcalculationhistory_cohort_id_e7c02b55",
            reverse_sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_cohortcalculationhistory_cohort_id_e7c02b55 ON posthog_cohortcalculationhistory (cohort_id)",
        ),
        migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_cohortcalculationhistory_team_id_beba9c96",
            reverse_sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_cohortcalculationhistory_team_id_beba9c96 ON posthog_cohortcalculationhistory (team_id)",
        ),
    ]
