"""
Dagster job that persists each team's resolved `personsOnEventsMode` into
`Team.modifiers["personsOnEventsMode"]`.

Background: `set_default_modifier_values` currently fills `personsOnEventsMode`
by evaluating a feature flag locally at request time. The local SDK flag-cache
state varies across web pods (cold-start, polling lag, regional hypercache
mis-pointing), so the same team can resolve to different values across pods.
That value flows into `get_cache_payload`, fragmenting the query cache_key
per-pod and breaking dashboard cache coherence.

This job evaluates the two PoE flags **server-side via the FF API** (using the
SDK's `Client.get_flags_decision`, which POSTs to `/flags/` directly without
consulting the local cache), so each team's persisted value matches the
canonical FF-service state regardless of worker SDK hydration.

Resolution rules:
  - v2 flag True   → person_id_override_properties_on_events  (PoE v2)
  - v1 flag True   → person_id_no_override_properties_on_events  (PoE v1)
  - both False/None → person_id_override_properties_on_events  (v2 fallback)

The "everything else → v2" fallback diverges from `team.person_on_events_mode_flag_based_default`,
which falls back to `PERSON_ID_OVERRIDE_PROPERTIES_JOINED`. Flag 8523 has been
at 100% rollout for orgs created after 2024-06-14 — every team created in the
last ~2 years already resolves to v2 — so this job adopts v2 as the canonical
modern default. The pre-2024-06-14 non-allowlisted population (~17% of teams)
silently shifts from JOINED to v2; if any of those teams need to stay on
JOINED, set the modifier explicitly before running.

Idempotent: skips teams that already have a value at
`team.modifiers["personsOnEventsMode"]`. Supports `dry_run` op config to log
what would be written without touching the DB.
"""

import dagster
import posthoganalytics
from posthoganalytics.client import Client

from posthog.schema import PersonsOnEventsMode

from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.models.team import Team

POE_V2_FLAG = "persons-on-events-v2-reads-enabled"
POE_V1_FLAG = "persons-on-events-person-id-no-override-properties-on-events"


def _resolve_persons_on_events_mode(team: Team, client: Client) -> PersonsOnEventsMode:
    """
    Resolve a team's mode using the FF API directly — no local SDK eval.

    `Client.get_flags_decision` POSTs to the `/flags/` endpoint with the team's
    group context and returns the canonical answer. The local definition cache
    is not consulted, so this is robust against the regional hypercache
    mis-pointing that motivated the cache_key fragmentation fix.

    The `PERSON_ON_EVENTS_*_OVERRIDE` env vars that the request-path resolver
    honors are deliberately ignored here — they're runtime knobs, not data.
    Encoding their result into `team.modifiers` would freeze the override into
    DB state, so unsetting the env var wouldn't restore each team's intended
    flag-driven mode.
    """
    decision = client.get_flags_decision(
        distinct_id=str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
                "created_at": team.organization.created_at.isoformat() if team.organization.created_at else None,
            },
            "project": {
                "id": str(team.id),
                "created_at": team.created_at.isoformat() if team.created_at else None,
                "uuid": str(team.uuid),
            },
        },
        flag_keys_to_evaluate=[POE_V2_FLAG, POE_V1_FLAG],
    )
    flags = decision.get("flags", {}) or {}

    v2_flag = flags.get(POE_V2_FLAG)
    if v2_flag and v2_flag.enabled:
        return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

    v1_flag = flags.get(POE_V1_FLAG)
    if v1_flag and v1_flag.enabled:
        return PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

    # Fallback: v2 (current platform default since the 2024-06-14 100% rollout).
    return PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS


@dagster.op(
    config_schema={
        "dry_run": dagster.Field(
            dagster.Bool,
            default_value=False,
            description="If True, log what would be written but don't touch the DB.",
        ),
    },
)
def persist_persons_on_events_mode_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> dict[str, int]:
    """For each team in the batch, persist its current personsOnEventsMode if not already set."""
    dry_run: bool = context.op_config["dry_run"]

    # Resolve the SDK client once per batch rather than per team. `setup()` is idempotent
    # (returns the existing default client if already initialized) but doing it in the
    # per-team hot path is wasteful and obscures the dependency.
    client = posthoganalytics.setup()

    # Pulls organization + created_at because they're sent as group_properties
    # to the FF service — fetching them up front avoids per-team queries.
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
    by_mode: dict[str, int] = {}

    for team in teams:
        existing_modifiers = team.modifiers or {}
        if existing_modifiers.get("personsOnEventsMode") is not None:
            skipped_already_set += 1
            continue

        try:
            resolved_mode = _resolve_persons_on_events_mode(team, client)
        except Exception as e:
            context.log.warning(f"team {team.id}: failed to resolve mode ({e!r}); skipping")
            skipped_errored += 1
            continue

        team.modifiers = {**existing_modifiers, "personsOnEventsMode": resolved_mode.value}
        teams_to_update.append(team)
        by_mode[resolved_mode.value] = by_mode.get(resolved_mode.value, 0) + 1

    updated = 0
    if teams_to_update and not dry_run:
        # bulk_update: modifiers is a JSON column, no signal handlers depend on
        # the previous value, and we don't need to bump updated_at on every team.
        updated = Team.objects.bulk_update(teams_to_update, fields=["modifiers"], batch_size=500)

    context.log.info(
        f"Batch: dry_run={dry_run}, would_update={len(teams_to_update)}, "
        f"updated={updated}, by_mode={by_mode}, "
        f"skipped_already_set={skipped_already_set}, skipped_errored={skipped_errored}, "
        f"not_found={not_found}"
    )
    context.add_output_metadata(
        {
            "dry_run": dagster.MetadataValue.bool(dry_run),
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "would_update": dagster.MetadataValue.int(len(teams_to_update)),
            "updated": dagster.MetadataValue.int(updated),
            "skipped_already_set": dagster.MetadataValue.int(skipped_already_set),
            "skipped_errored": dagster.MetadataValue.int(skipped_errored),
            "not_found": dagster.MetadataValue.int(not_found),
            "by_mode": dagster.MetadataValue.json(by_mode),
        }
    )

    return {
        "would_update": len(teams_to_update),
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
    """Aggregate results from all batches and emit run-level Dagster metadata."""
    totals = {
        k: sum(r.get(k, 0) for r in results)
        for k in ("would_update", "updated", "skipped_already_set", "skipped_errored", "not_found")
    }
    context.log.info(f"Job complete: {totals}")
    context.add_output_metadata({k: dagster.MetadataValue.int(v) for k, v in totals.items()})


@dagster.job(
    description=(
        "Persist each team's resolved `personsOnEventsMode` into `team.modifiers` so the "
        "value is read from a single source of truth instead of per-pod feature-flag "
        "evaluation. Eliminates query-cache_key fragmentation. "
        "Set ops.persist_persons_on_events_mode_op.config.dry_run=True to preview."
    ),
    tags={"owner": JobOwners.TEAM_QUERY_PERFORMANCE.value},
)
def backfill_persons_on_events_mode_job():
    team_ids = get_all_team_ids_op()
    results = team_ids.map(persist_persons_on_events_mode_op)
    aggregate_persons_on_events_mode_results_op(results.collect())
