from datetime import timedelta
from typing import TYPE_CHECKING

import temporalio

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import (
    delete_schedule,
    pause_schedule,
    schedule_exists,
    trigger_schedule,
    unpause_schedule,
)

if TYPE_CHECKING:
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


def delete_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=str(saved_query.id))
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def pause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=str(saved_query.id))


def unpause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=str(saved_query.id))
    # reset the automatic sync interval for rev analytics
    viewset = saved_query.managed_viewset
    if viewset and viewset.kind == "revenue_analytics":
        previous_interval = saved_query.sync_frequency_interval
        new_interval = timedelta(hours=12)
        saved_query.sync_frequency_interval = new_interval
        saved_query.save()
        if previous_interval != new_interval:
            log_activity(
                organization_id=saved_query.team.organization_id,
                team_id=saved_query.team_id,
                user=None,
                was_impersonated=False,
                item_id=saved_query.id,
                scope="DataWarehouseSavedQuery",
                activity="sync_frequency_reset",
                detail=Detail(
                    name=saved_query.name,
                    changes=[
                        Change(
                            field="sync_frequency_interval",
                            action="changed",
                            type="DataWarehouseSavedQuery",
                            before=str(previous_interval) if previous_interval else None,
                            after=str(new_interval),
                        ),
                    ],
                ),
            )


def saved_query_workflow_exists(saved_query: "DataWarehouseSavedQuery") -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=str(saved_query.id))


def trigger_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id))
