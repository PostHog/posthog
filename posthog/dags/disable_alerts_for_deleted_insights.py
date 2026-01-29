from collections import defaultdict

import dagster

from posthog.dags.common import JobOwners


class DeleteAlertsConfig(dagster.Config):
    dry_run: bool = True
    limit: int = 1000


@dagster.op
def delete_alerts_for_deleted_insights_op(
    context: dagster.OpExecutionContext,
    config: DeleteAlertsConfig,
) -> dict[str, int]:
    """Delete alerts that are associated with soft-deleted insights.

    This is a backfill operation to clean up alerts on insights that were deleted
    before the automatic cleanup logic was added.
    """
    from posthog.models import AlertConfiguration

    alerts_on_deleted = AlertConfiguration.objects.filter(insight__deleted=True)[: config.limit]

    count = alerts_on_deleted.count()
    context.log.info(f"Found {count} alerts on deleted insights")

    if count == 0:
        context.log.info("No alerts to delete")
        context.add_output_metadata(
            {
                "total_found": dagster.MetadataValue.int(0),
                "total_deleted": dagster.MetadataValue.int(0),
            }
        )
        return {"total_found": 0, "total_deleted": 0}

    alerts_by_team: dict[int, list] = defaultdict(list)
    for alert in alerts_on_deleted:
        alerts_by_team[alert.team_id].append(alert)

    context.log.info(f"Alerts to delete by team ({count} total across {len(alerts_by_team)} teams):")
    for team_id, team_alerts in sorted(alerts_by_team.items(), key=lambda x: -len(x[1])):
        insight_ids = [str(a.insight_id) for a in team_alerts[:10]]
        insight_preview = ", ".join(insight_ids)
        if len(team_alerts) > 10:
            insight_preview += f", ... (+{len(team_alerts) - 10} more)"
        context.log.info(f"  Team {team_id}: {len(team_alerts)} alerts (insights: {insight_preview})")

    if config.dry_run:
        context.log.warning(f"DRY RUN: Would delete {count} alerts (not making changes)")
        context.add_output_metadata(
            {
                "total_found": dagster.MetadataValue.int(count),
                "total_deleted": dagster.MetadataValue.int(0),
            }
        )
        return {"total_found": count, "total_deleted": 0}

    # Actually delete the alerts (this will cascade delete related objects)
    deleted_count, _ = alerts_on_deleted.delete()
    context.log.info(f"Successfully deleted {deleted_count} alerts")

    # Add metadata for Dagster UI
    context.add_output_metadata(
        {
            "total_found": dagster.MetadataValue.int(count),
            "total_deleted": dagster.MetadataValue.int(deleted_count),
        }
    )

    return {"total_found": count, "total_deleted": deleted_count}


@dagster.job(tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value})
def delete_alerts_for_deleted_insights():
    delete_alerts_for_deleted_insights_op()
