from typing import TYPE_CHECKING

from django.db.models import OuterRef, Q, QuerySet, Subquery

from products.data_modeling.backend.facade.enums import DataModelingJobEngine
from products.data_modeling.backend.logic.node_visibility import exclude_hidden_nodes
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.node import Node

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_LAST_RUN_FAILED = Q(_latest_job_status=DataModelingJob.Status.FAILED) | Q(
    _latest_job_status__isnull=True, properties__system__last_run_status=DataModelingJob.Status.FAILED
)
_SERVING_SUSPENDED = Q(properties__system__suspended__has_key=DataModelingJobEngine.CLICKHOUSE)


def _with_latest_serving_status(nodes: QuerySet[Node]) -> QuerySet[Node]:
    serving_jobs = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("saved_query_id"), engine=DataModelingJobEngine.CLICKHOUSE
    ).order_by("-last_run_at")
    return nodes.annotate(_latest_job_status=Subquery(serving_jobs.values("status")[:1]))


def failing_model_count(team: "Team", user_access_control: "UserAccessControl") -> int | None:
    """Models the caller's list shows that failed their last run or are suspended, or None without warehouse read access."""
    if not user_access_control.check_access_level_for_resource("warehouse_view", required_level="viewer"):
        return None
    nodes = exclude_hidden_nodes(Node.objects.filter(team_id=team.id), team, user_access_control)
    return _with_latest_serving_status(nodes).filter(_LAST_RUN_FAILED | _SERVING_SUSPENDED).count()
