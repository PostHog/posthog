from typing import TYPE_CHECKING

from django.db.models import Q

from products.data_modeling.backend.facade.enums import DataModelingJobEngine
from products.data_modeling.backend.logic.node_reads import _visible_nodes, _with_latest_serving_job
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_LAST_RUN_FAILED = Q(_latest_job_status=DataModelingJob.Status.FAILED) | Q(
    _latest_job_status__isnull=True, properties__system__last_run_status=DataModelingJob.Status.FAILED
)
_SERVING_SUSPENDED = Q(properties__system__suspended__has_key=DataModelingJobEngine.CLICKHOUSE)


def failing_model_count(team: "Team", user_access_control: "UserAccessControl") -> int | None:
    """Models the caller's list shows that failed their last run or are suspended, or None without warehouse read access."""
    if not user_access_control.check_access_level_for_resource("warehouse_view", required_level="viewer"):
        return None
    nodes = _with_latest_serving_job(_visible_nodes(team, user_access_control))
    return nodes.filter(_LAST_RUN_FAILED | _SERVING_SUSPENDED).count()
