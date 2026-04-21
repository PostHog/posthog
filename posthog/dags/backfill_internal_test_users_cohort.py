import dagster

from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.models.cohort import Cohort
from posthog.models.cohort.cohort import INTERNAL_TEST_USERS_COHORT_NAME, CohortKind
from posthog.models.team import Team

# Standard filter: matches people with $internal_or_test_user set to true
_INTERNAL_TEST_USERS_FILTERS: dict = {
    "properties": {
        "type": "OR",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "$internal_or_test_user",
                        "type": "person",
                        "value": [True],
                        "operator": "exact",
                    }
                ],
            }
        ],
    }
}


@dagster.op
def create_internal_test_users_cohorts_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> dict[str, int]:
    """Create internal/test users cohort for teams that don't already have one."""

    # Find teams that already have the cohort so we can skip them in bulk
    teams_with_cohort = set(
        Cohort.objects.filter(
            team_id__in=team_ids,
            kind=CohortKind.INTERNAL_TEST_USERS,
        ).values_list("team_id", flat=True)
    )

    # Bulk-fetch only teams that need a cohort
    teams_needing_cohort = list(Team.objects.filter(id__in=[tid for tid in team_ids if tid not in teams_with_cohort]))

    not_found = len(team_ids) - len(teams_with_cohort) - len(teams_needing_cohort)
    if not_found > 0:
        context.log.warning(f"{not_found} team IDs not found in the database, skipping")

    # Bulk-create all cohorts in a single INSERT.
    # No race condition: the INTERNAL_TEST_USERS kind can only be set by this
    # backfill (or get_or_create_internal_test_users_cohort), not by users
    # through the UI, so no concurrent creation can happen.
    cohorts_to_create = [
        Cohort(
            team=team,
            name=INTERNAL_TEST_USERS_COHORT_NAME,
            description="People who are internal team members or test users. Used for filtering out internal traffic from analytics.",
            is_static=False,
            kind=CohortKind.INTERNAL_TEST_USERS,
            filters=_INTERNAL_TEST_USERS_FILTERS,
        )
        for team in teams_needing_cohort
    ]

    created_cohorts = Cohort.objects.bulk_create(cohorts_to_create)
    created = len(created_cohorts)
    skipped = len(teams_with_cohort) + not_found

    context.log.info(f"Batch complete: {created} created, {skipped} skipped")
    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "created": dagster.MetadataValue.int(created),
            "skipped": dagster.MetadataValue.int(skipped),
        }
    )

    return {"created": created, "skipped": skipped}


@dagster.op
def aggregate_cohort_results_op(
    context: dagster.OpExecutionContext,
    results: list[dict[str, int]],
) -> None:
    """Aggregate results from all batches."""
    total_created = sum(r["created"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)

    context.log.info(f"Completed: {total_created} created, {total_skipped} skipped")

    context.add_output_metadata(
        {
            "total_created": dagster.MetadataValue.int(total_created),
            "total_skipped": dagster.MetadataValue.int(total_skipped),
        }
    )


@dagster.job(
    description="Creates internal/test users cohort for all teams that don't already have one",
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value},
)
def backfill_internal_test_users_cohort_job():
    team_ids = get_all_team_ids_op()
    results = team_ids.map(create_internal_test_users_cohorts_op)
    aggregate_cohort_results_op(results.collect())
