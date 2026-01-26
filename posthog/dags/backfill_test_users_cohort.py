"""Backfill job to create 'Test users' system cohort for existing teams."""

import dagster

from posthog.dags.common import JobOwners
from posthog.models.cohort.cohort import Cohort, SystemCohortType, create_system_cohorts
from posthog.models.team.team import Team


class BackfillTestUsersCohortConfig(dagster.Config):
    """Configuration for the backfill test users cohort job."""

    batch_size: int = 100


@dagster.op
def get_teams_without_test_users_cohort(
    context: dagster.OpExecutionContext,
) -> list[int]:
    """Get team IDs that don't have a 'Test users' system cohort."""
    teams_with_cohort = Cohort.objects.filter(system_type=SystemCohortType.TEST_USERS).values_list("team_id", flat=True)

    teams_without_cohort = Team.objects.exclude(id__in=teams_with_cohort).values_list("id", flat=True)

    team_ids = list(teams_without_cohort)
    context.log.info(f"Found {len(team_ids)} teams without test users cohort")
    return team_ids


@dagster.op
def create_team_chunks(
    context: dagster.OpExecutionContext,
    config: BackfillTestUsersCohortConfig,
    team_ids: list[int],
) -> list[list[int]]:
    """Split team IDs into chunks for parallel processing."""
    chunks = [team_ids[i : i + config.batch_size] for i in range(0, len(team_ids), config.batch_size)]
    context.log.info(f"Created {len(chunks)} chunks of up to {config.batch_size} teams")
    return chunks


@dagster.op(out=dagster.DynamicOut())
def fan_out_chunks(
    context: dagster.OpExecutionContext,
    chunks: list[list[int]],
):
    """Fan out chunks for parallel processing."""
    for i, chunk in enumerate(chunks):
        yield dagster.DynamicOutput(chunk, mapping_key=f"chunk_{i}")


@dagster.op
def create_test_users_cohort_for_chunk(
    context: dagster.OpExecutionContext,
    chunk: list[int],
) -> int:
    """Create test users cohort for a chunk of teams.

    Idempotent: skips teams that already have a test users cohort.
    """
    created_count = 0
    for team_id in chunk:
        team = Team.objects.get(id=team_id)
        if Cohort.objects.filter(team=team, system_type=SystemCohortType.TEST_USERS).exists():
            context.log.info(f"Team {team_id} already has test users cohort, skipping")
            continue
        create_system_cohorts(team)
        created_count += 1
        context.log.info(f"Created test users cohort for team {team_id}")

    return created_count


@dagster.op
def aggregate_results(
    context: dagster.OpExecutionContext,
    results: list[int],
) -> int:
    """Aggregate results from all chunks."""
    total_created = sum(results)
    context.log.info(f"Total cohorts created: {total_created}")
    return total_created


@dagster.job(tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value})
def backfill_test_users_cohort():
    """
    Backfill job to create 'Test users' system cohort for all existing teams
    that don't already have one.

    This job does NOT modify existing teams' test_account_filters - only new
    teams get the cohort added to their filters automatically.
    """
    team_ids = get_teams_without_test_users_cohort()
    chunks = create_team_chunks(team_ids)
    fan_out = fan_out_chunks(chunks)
    results = fan_out.map(create_test_users_cohort_for_chunk)
    aggregate_results(results.collect())
