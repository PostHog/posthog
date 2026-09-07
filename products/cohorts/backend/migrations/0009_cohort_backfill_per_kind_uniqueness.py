from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently

ACTIVE_STATUSES = ("awaiting_boundary", "blocked", "seeding", "reconciling")
COHORT_WHERE = "WHERE cohort_id IS NOT NULL AND status IN ('awaiting_boundary', 'blocked', 'seeding', 'reconciling')"
TEAM_WHERE = "WHERE scope = 'team' AND status IN ('awaiting_boundary', 'blocked', 'seeding', 'reconciling')"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cohorts", "0008_person_property_backfill_foundation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="cohortbackfillrun",
                    constraint=models.UniqueConstraint(
                        fields=("cohort", "backfill_kind"),
                        condition=models.Q(cohort__isnull=False, status__in=ACTIVE_STATUSES),
                        name="cohort_bfr_active_cohort_kind_uq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="cohort_bfr_active_cohort_kind_uq",
                    table_name="cohort_backfill_runs",
                    columns="(cohort_id, backfill_kind)",
                    unique=True,
                    where=COHORT_WHERE,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="cohortbackfillrun",
                    constraint=models.UniqueConstraint(
                        fields=("team", "backfill_kind"),
                        condition=models.Q(scope="team", status__in=ACTIVE_STATUSES),
                        name="cohort_bfr_active_team_kind_uq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="cohort_bfr_active_team_kind_uq",
                    table_name="cohort_backfill_runs",
                    columns="(team_id, backfill_kind)",
                    unique=True,
                    where=TEAM_WHERE,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="cohortbackfillrun",
                    name="cohort_bfr_active_cohort_uq",
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="cohort_bfr_active_cohort_uq",
                    table_name="cohort_backfill_runs",
                    columns="(cohort_id)",
                    unique=True,
                    where=COHORT_WHERE,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="cohortbackfillrun",
                    name="cohort_bfr_active_team_uq",
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="cohort_bfr_active_team_uq",
                    table_name="cohort_backfill_runs",
                    columns="(team_id)",
                    unique=True,
                    where=TEAM_WHERE,
                ),
            ],
        ),
    ]
