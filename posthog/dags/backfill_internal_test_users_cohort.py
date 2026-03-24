import dagster

from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.exceptions_capture import capture_exception


@dagster.op
def create_internal_test_users_cohorts_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> dict[str, int]:
    """Create internal/test users cohort for teams that don't already have one."""
    from posthog.models.cohort import Cohort
    from posthog.models.cohort.cohort import CohortKind, get_or_create_internal_test_users_cohort
    from posthog.models.team import Team

    # Find teams that already have the cohort so we can skip them in bulk
    teams_with_cohort = set(
        Cohort.objects.filter(
            team_id__in=team_ids,
            kind=CohortKind.INTERNAL_TEST_USERS,
        ).values_list("team_id", flat=True)
    )

    created = 0
    skipped = len(teams_with_cohort)
    failed = 0

    for team_id in team_ids:
        if team_id in teams_with_cohort:
            continue

        try:
            team = Team.objects.get(id=team_id)
            get_or_create_internal_test_users_cohort(team)
            created += 1
            context.log.info(f"Created internal/test users cohort for team {team_id}")
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found, skipping")
            skipped += 1
        except Exception as e:
            context.log.exception(f"Failed to create cohort for team {team_id}")
            capture_exception(e, {"team_id": team_id})
            failed += 1

    context.log.info(f"Batch complete: {created} created, {skipped} skipped, {failed} failed")
    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "created": dagster.MetadataValue.int(created),
            "skipped": dagster.MetadataValue.int(skipped),
            "failed": dagster.MetadataValue.int(failed),
        }
    )

    return {"created": created, "skipped": skipped, "failed": failed}


@dagster.op
def aggregate_cohort_results_op(
    context: dagster.OpExecutionContext,
    results: list[dict[str, int]],
) -> None:
    """Aggregate results from all batches."""
    total_created = sum(r["created"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_failed = sum(r["failed"] for r in results)

    context.log.info(f"Completed: {total_created} created, {total_skipped} skipped, {total_failed} failed")

    context.add_output_metadata(
        {
            "total_created": dagster.MetadataValue.int(total_created),
            "total_skipped": dagster.MetadataValue.int(total_skipped),
            "total_failed": dagster.MetadataValue.int(total_failed),
        }
    )

    if total_failed > 0:
        raise Exception(f"Failed to create internal/test users cohort for {total_failed} teams")


@dagster.job(
    description="Creates internal/test users cohort for all teams that don't already have one",
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value},
)
def backfill_internal_test_users_cohort_job():
    team_ids = get_all_team_ids_op()
    results = team_ids.map(create_internal_test_users_cohorts_op)
    aggregate_cohort_results_op(results.collect())
