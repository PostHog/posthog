"""
Dagster job that persists each team's resolved `personsOnEventsMode` into
`Team.modifiers["personsOnEventsMode"]`.

Background: until recently, `set_default_modifier_values` filled
`personsOnEventsMode` by evaluating a local feature flag at request time. The
local SDK flag-cache state varies across web pods (cold-start, polling lag,
transient failures), so the same team could resolve to different values across
pods. That value flows into `get_cache_payload`, fragmenting the query cache_key
per-pod and breaking dashboard cache coherence.

The fix removes the flag eval from the cache_key path and reads
`team.modifiers["personsOnEventsMode"]` instead. This job populates that field
for every team that has not yet been backfilled, using the team's CURRENT
flag-resolved value so behavior is preserved on a per-team basis. After the job
completes platform-wide, the cache_key for any given query is fully
deterministic across pods.

Idempotent: skips teams that already have `personsOnEventsMode` set.
"""

import dagster

from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.models.team import Team


@dagster.op
def persist_persons_on_events_mode_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> dict[str, int]:
    """For each team in the batch, persist its current `personsOnEventsMode` into `team.modifiers`."""

    teams = list(Team.objects.filter(id__in=team_ids).only("id", "modifiers"))
    not_found = len(team_ids) - len(teams)
    if not_found > 0:
        context.log.warning(f"{not_found} team IDs not found in the database, skipping")

    teams_to_update: list[Team] = []
    skipped_already_set = 0
    skipped_errored = 0

    for team in teams:
        existing_modifiers = team.modifiers or {}
        if existing_modifiers.get("personsOnEventsMode") is not None:
            skipped_already_set += 1
            continue

        try:
            # Resolve via the team property (consults env override + feature flag locally)
            # and freeze the result. Each team gets the value its current code path would
            # have produced — this is intentional: we are persisting current behavior, not
            # changing it.
            resolved_mode = team.person_on_events_mode_flag_based_default
        except Exception as e:
            context.log.warning(f"team {team.id}: failed to resolve mode ({e}), skipping")
            skipped_errored += 1
            continue

        team.modifiers = {**existing_modifiers, "personsOnEventsMode": resolved_mode.value}
        teams_to_update.append(team)

    updated = 0
    if teams_to_update:
        # bulk_update is fine here: `modifiers` is a JSON column, no signal handlers
        # depend on the previous value, and we don't need to bump `updated_at`.
        updated = Team.objects.bulk_update(teams_to_update, fields=["modifiers"], batch_size=500)

    context.log.info(
        f"Batch complete: {updated} updated, {skipped_already_set} already set, "
        f"{skipped_errored} errored, {not_found} not found"
    )
    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "updated": dagster.MetadataValue.int(updated),
            "skipped_already_set": dagster.MetadataValue.int(skipped_already_set),
            "skipped_errored": dagster.MetadataValue.int(skipped_errored),
            "not_found": dagster.MetadataValue.int(not_found),
        }
    )

    return {
        "updated": updated,
        "skipped_already_set": skipped_already_set,
        "skipped_errored": skipped_errored,
        "not_found": not_found,
    }


@dagster.op
def aggregate_persons_on_events_mode_results_op(
    context: dagster.OpExecutionContext,
    results: list[dict[str, int]],
) -> None:
    """Aggregate results from all batches."""
    totals = {
        "updated": sum(r["updated"] for r in results),
        "skipped_already_set": sum(r["skipped_already_set"] for r in results),
        "skipped_errored": sum(r["skipped_errored"] for r in results),
        "not_found": sum(r["not_found"] for r in results),
    }

    context.log.info(
        f"Completed: {totals['updated']} updated, "
        f"{totals['skipped_already_set']} already set, "
        f"{totals['skipped_errored']} errored, {totals['not_found']} not found"
    )

    context.add_output_metadata({k: dagster.MetadataValue.int(v) for k, v in totals.items()})


@dagster.job(
    description=(
        "Persists each team's resolved `personsOnEventsMode` into `Team.modifiers` so the "
        "value is read from a single source of truth instead of per-pod feature-flag "
        "evaluation. Eliminates cache_key fragmentation across web pods."
    ),
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value},
)
def backfill_persons_on_events_mode_job():
    team_ids = get_all_team_ids_op()
    results = team_ids.map(persist_persons_on_events_mode_op)
    aggregate_persons_on_events_mode_results_op(results.collect())
