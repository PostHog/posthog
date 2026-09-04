import asyncio

from django.conf import settings

from temporalio import activity

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.event_retention import organization_events_retention_months
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput, SyncEventsRetentionResult

LOGGER = get_write_only_logger()


def _capture_retention_changes(changes: list[dict]) -> None:
    with ph_scoped_capture() as capture:
        for change in changes:
            capture(
                distinct_id="sync-events-retention",
                event="events_retention_changed",
                properties={
                    **change,
                    "cloud_deployment": settings.CLOUD_DEPLOYMENT,
                    # Personless: a mass change (e.g. a policy flip) must not mint one person per team.
                    "$process_person_profile": False,
                },
            )


@activity.defn(name="sync-events-retention")
async def sync_events_retention(input: SyncEventsRetentionInput) -> SyncEventsRetentionResult:
    """Reconcile every team's events retention window with its billing entitlement.

    Events retention is plan-derived and not user-editable, so we set it outright — unlike replay enforcement, which
    only caps a user-chosen value. Teams with no entitlement default to 7 years, grandfathering existing paid teams.
    """
    async with Heartbeater():
        logger = LOGGER.bind()
        logger.info("Syncing events retention for all teams...")

        last_pk = 0
        total_processed = 0
        total_updated = 0
        # Teams far outnumber organizations, so parse each org's entitlement once and reuse it across every team it
        # owns instead of decompressing the same TOASTed JSONB blob once per team. Kept across batches because teams
        # order by pk, not by organization, so one org spans many pages.
        org_target_months: dict[int, int] = {}

        while True:
            # Bounded keyset batches: pgbouncer disables server-side cursors, so iterating the full queryset
            # would materialize every team in memory at once.
            teams = [
                team
                async for team in Team.objects.filter(pk__gt=last_pk)
                .order_by("pk")
                .only("id", "event_retention_months", "organization")[: input.batch_size]
            ]
            if not teams:
                break
            last_pk = teams[-1].pk

            missing_org_ids = {team.organization_id for team in teams if team.organization_id not in org_target_months}
            if missing_org_ids:
                async for org in Organization.objects.filter(id__in=missing_org_ids).only(
                    "id", "available_product_features"
                ):
                    org_target_months[org.id] = organization_events_retention_months(org)

            teams_to_update: list[Team] = []
            changes: list[dict] = []
            for team in teams:
                target_months = org_target_months.get(team.organization_id)
                if target_months is None:
                    # Orphaned FK — the org row is gone. Skip rather than crash the nightly run.
                    continue
                if team.event_retention_months != target_months:
                    changes.append(
                        {
                            "team_id": team.pk,
                            "organization_id": str(team.organization_id),
                            "retention_months_before": team.event_retention_months,
                            "retention_months_after": target_months,
                        }
                    )
                    team.event_retention_months = target_months
                    teams_to_update.append(team)

            if teams_to_update and not input.dry_run:
                await Team.objects.abulk_update(teams_to_update, ["event_retention_months"])
                # Per batch and off-thread so a mass change can't stall heartbeats or overflow the client queue.
                await asyncio.to_thread(_capture_retention_changes, changes)

            total_processed += len(teams)
            total_updated += len(teams_to_update)
            logger.info(f"Processed {total_processed} teams, {total_updated} updated so far...")

        if input.dry_run:
            logger.info(f"DRY RUN: Would have updated {total_updated} of {total_processed} teams")
        else:
            logger.info(f"Updated {total_updated} of {total_processed} teams")

        return SyncEventsRetentionResult(total_processed=total_processed, total_updated=total_updated)
