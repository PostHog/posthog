import asyncio

from django.conf import settings
from django.utils import timezone

from temporalio import activity

from posthog.constants import AvailableFeature
from posthog.models.team import Team, TeamEventsRetentionGrant
from posthog.models.team.event_retention import events_retention_target_months, parse_events_feature_to_months
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

        while True:
            # Bounded keyset batches: pgbouncer disables server-side cursors, so iterating the full queryset
            # would materialize every team (with its joined organization row) in memory at once.
            teams = [
                team
                async for team in Team.objects.filter(pk__gt=last_pk)
                .order_by("pk")
                .select_related("organization")
                .only("id", "event_retention_months", "organization__available_product_features")[: input.batch_size]
            ]
            if not teams:
                break
            last_pk = teams[-1].pk
            grant_months_by_team = {
                grant.team_id: grant.retention_months
                async for grant in TeamEventsRetentionGrant.objects.filter(team_id__in=[team.pk for team in teams])
            }

            team_ids_by_change: dict[tuple[int, int], list[int]] = {}
            changes: list[dict] = []
            for team in teams:
                retention_feature = team.organization.get_available_feature(
                    AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION
                )
                target_months = events_retention_target_months(
                    parse_events_feature_to_months(retention_feature), grant_months_by_team.get(team.pk)
                )
                if team.event_retention_months != target_months:
                    changes.append(
                        {
                            "team_id": team.pk,
                            "organization_id": str(team.organization_id),
                            "retention_months_before": team.event_retention_months,
                            "retention_months_after": target_months,
                        }
                    )
                    team_ids_by_change.setdefault((team.event_retention_months, target_months), []).append(team.pk)

            batch_updated = 0
            if input.dry_run:
                batch_updated = len(changes)
            elif team_ids_by_change:
                updated_at = timezone.now()
                for (current_months, target_months), team_ids in team_ids_by_change.items():
                    # Only rows still at the value read above, so a grant saved in between keeps its window.
                    batch_updated += await Team.objects.filter(
                        pk__in=team_ids, event_retention_months=current_months
                    ).aupdate(event_retention_months=target_months, updated_at=updated_at)
                # Per batch and off-thread so a mass change can't stall heartbeats or overflow the client queue.
                await asyncio.to_thread(_capture_retention_changes, changes)

            total_processed += len(teams)
            total_updated += batch_updated
            logger.info(f"Processed {total_processed} teams, {total_updated} updated so far...")

        if input.dry_run:
            logger.info(f"DRY RUN: Would have updated {total_updated} of {total_processed} teams")
        else:
            logger.info(f"Updated {total_updated} of {total_processed} teams")

        return SyncEventsRetentionResult(total_processed=total_processed, total_updated=total_updated)
