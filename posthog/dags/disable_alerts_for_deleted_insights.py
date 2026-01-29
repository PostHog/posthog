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

    total_count = AlertConfiguration.objects.filter(insight__deleted=True).count()
    alert_ids = list(
        AlertConfiguration.objects.filter(insight__deleted=True).values_list("id", flat=True)[: config.limit]
    )
    batch_count = len(alert_ids)

    context.log.info(f"Found {total_count} total alerts on deleted insights, processing batch of {batch_count}")

    if batch_count == 0:
        context.log.info("No alerts to delete")
        context.add_output_metadata(
            {
                "total_found": dagster.MetadataValue.int(0),
                "batch_size": dagster.MetadataValue.int(0),
                "total_deleted": dagster.MetadataValue.int(0),
            }
        )
        return {"total_found": 0, "total_deleted": 0}

    # Fetch full objects for logging (only the batch we're deleting)
    alerts_to_delete = AlertConfiguration.objects.filter(id__in=alert_ids)
    alerts_by_team: dict[int, list] = defaultdict(list)
    for alert in alerts_to_delete:
        alerts_by_team[alert.team_id].append(alert)

    context.log.info(f"Alerts to delete by team ({batch_count} in batch across {len(alerts_by_team)} teams):")
    for team_id, team_alerts in sorted(alerts_by_team.items(), key=lambda x: -len(x[1])):
        insight_ids = [str(a.insight_id) for a in team_alerts[:10]]
        insight_preview = ", ".join(insight_ids)
        if len(team_alerts) > 10:
            insight_preview += f", ... (+{len(team_alerts) - 10} more)"
        context.log.info(f"  Team {team_id}: {len(team_alerts)} alerts (insights: {insight_preview})")

    if config.dry_run:
        context.log.warning(f"DRY RUN: Would delete {batch_count} alerts (not making changes)")
        context.add_output_metadata(
            {
                "total_found": dagster.MetadataValue.int(total_count),
                "batch_size": dagster.MetadataValue.int(batch_count),
                "total_deleted": dagster.MetadataValue.int(0),
            }
        )
        return {"total_found": total_count, "total_deleted": 0}

    deleted_count, _ = alerts_to_delete.delete()
    context.log.info(f"Successfully deleted {deleted_count} alerts ({total_count - deleted_count} remaining)")

    context.add_output_metadata(
        {
            "total_found": dagster.MetadataValue.int(total_count),
            "batch_size": dagster.MetadataValue.int(batch_count),
            "total_deleted": dagster.MetadataValue.int(deleted_count),
        }
    )

    return {"total_found": total_count, "total_deleted": deleted_count}


@dagster.job(tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value})
def delete_alerts_for_deleted_insights():
    delete_alerts_for_deleted_insights_op()
