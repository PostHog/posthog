import dagster

from posthog.dags.common import JobOwners


class DeleteAlertsConfig(dagster.Config):
    """Configuration for deleting alerts on deleted insights."""

    dry_run: bool = False
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

    # Find all alerts on deleted insights (both enabled and disabled)
    alerts_on_deleted = AlertConfiguration.objects.filter(
        insight__deleted=True,
    )[: config.limit]

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

    # Log sample alerts for visibility
    sample_size = min(20, count)
    sample_alerts = list(alerts_on_deleted[:sample_size])
    context.log.info(f"Sample of alerts (showing first {sample_size}):")
    for alert in sample_alerts:
        context.log.info(f"  - Alert {alert.id}: {alert.name} (insight {alert.insight_id}, team {alert.team_id})")

    if count > sample_size:
        context.log.info(f"  ... and {count - sample_size} more")

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
    """Backfill job to delete alerts for soft-deleted insights.

    This job can be triggered manually from the Dagster UI with configuration:
    - dry_run: Set to true to preview changes without making them
    - limit: Maximum number of alerts to process in one run (default: 1000)

    Example configuration in Dagster UI:
    {
        "ops": {
            "delete_alerts_for_deleted_insights_op": {
                "config": {
                    "dry_run": true,
                    "limit": 1000
                }
            }
        }
    }
    """
    delete_alerts_for_deleted_insights_op()
