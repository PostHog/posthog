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

Important: this job evaluates flags SERVER-SIDE (without `only_evaluate_locally`),
unlike the team property it replaces. The team property uses local-only eval to
avoid per-request latency, but local-only is itself the source of the variance
this job is meant to resolve. A cold Dagster worker would otherwise persist the
fall-through default for every team, silently migrating teams off their intended
mode. Server-side eval consults the flag service directly so each team gets its
canonical resolved value regardless of SDK hydration state in the worker.

Idempotent: skips teams that already have `personsOnEventsMode` set.
"""

from django.conf import settings

import dagster
import posthoganalytics

from posthog.schema import PersonsOnEventsMode

from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team


def _resolve_persons_on_events_mode_server_side(team: Team) -> PersonsOnEventsMode:
    """
    Evaluate the same two flags `team.person_on_events_mode_flag_based_default` consults,
    but server-side (no `only_evaluate_locally`). Used by the backfill so the persisted
    value is determined by the flag service's canonical state, not the worker's local
    SDK hydration state.
    """
    # Env overrides short-circuit any flag eval — same as the team property.
    v2_override = getattr(settings, "PERSON_ON_EVENTS_V2_OVERRIDE", None)
    poe_override = getattr(settings, "PERSON_ON_EVENTS_OVERRIDE", None)

    if is_cloud():
        v2_enabled = (
            v2_override
            if v2_override is not None
            else posthoganalytics.feature_enabled(
                "persons-on-events-v2-reads-enabled",
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                group_properties={
                    "organization": {
                        "id": str(team.organization_id),
                        "created_at": team.organization.created_at.isoformat()
                        if team.organization.created_at
                        else None,
                    }
                },
                send_feature_flag_events=False,
            )
        )
        if v2_enabled:
            return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

        poe_enabled = (
            poe_override
            if poe_override is not None
            else posthoganalytics.feature_enabled(
                "persons-on-events-person-id-no-override-properties-on-events",
                str(team.uuid),
                groups={"project": str(team.id)},
                group_properties={
                    "project": {
                        "id": str(team.id),
                        "created_at": team.created_at.isoformat() if team.created_at else None,
                        "uuid": team.uuid,
                    }
                },
                send_feature_flag_events=False,
            )
        )
        if poe_enabled:
            return PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

        return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED

    # Self-hosted: instance settings only, no SDK involvement (no variance to resolve).
    if v2_override if v2_override is not None else get_instance_setting("PERSON_ON_EVENTS_V2_ENABLED"):
        return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
    if poe_override if poe_override is not None else get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
        return PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
    return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED


@dagster.op
def persist_persons_on_events_mode_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> dict[str, int]:
    """For each team in the batch, persist its current `personsOnEventsMode` into `team.modifiers`."""

    # Pulls `organization` and `created_at` because server-side flag eval includes them
    # as group_properties — fetching them up front avoids per-team queries during eval.
    teams = list(
        Team.objects.filter(id__in=team_ids)
        .select_related("organization")
        .only(
            "id",
            "uuid",
            "modifiers",
            "organization_id",
            "created_at",
            "organization__id",
            "organization__created_at",
        )
    )
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
            # Server-side flag eval — no `only_evaluate_locally`. See module docstring.
            resolved_mode = _resolve_persons_on_events_mode_server_side(team)
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
