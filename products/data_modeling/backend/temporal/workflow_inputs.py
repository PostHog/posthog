"""
The inputs and ids that web code needs to start data_modeling workflows.

This module imports only the standard library and the product's enums. The workflow modules import
the activities, and those import the warehouse sources, so web code imports from here instead of
from the workflows.
"""

import uuid
import datetime as dt
import dataclasses

from products.data_modeling.backend.facade.enums import MaterializationRunTrigger

# Under a day, so a run that uses its whole budget still ends before the next daily shadow starts.
TRINO_SHADOW_RUN_TIMEOUT = dt.timedelta(hours=23)


def trino_shadow_workflow_id(workflow_id: str, dag_id: str) -> str:
    """The fixed id of the Trino shadow run for the DAG run with this workflow id.

    Tier schedule runs are `execute-dag-{dag_id}:{tier}-{timestamp}`, so each cadence tier gets
    its own shadow id. Any other run shares one id per DAG. A fixed id lets Temporal refuse a
    second shadow while the previous one is still running.
    """
    tier_prefix = f"execute-dag-{dag_id}:"
    if workflow_id.startswith(tier_prefix):
        tier = workflow_id[len(tier_prefix) :].split("-", 1)[0]
        if tier:
            return f"execute-dag-trino-{dag_id}:{tier}"
    return f"execute-dag-trino-{dag_id}"


def trino_build_workflow_id(dag_id: str, node_id: str) -> str:
    """The fixed id of the Trino build of one node.

    Temporal runs one workflow per id at a time, so a second run that reaches this node while the
    first still builds it cannot start a build of its own. Cancelling a Trino build does not stop
    its SQL, so this refusal is the only thing that keeps two runs from writing one table at once.
    The `materialize-view-{dag_id}-{node_id}` prefix is shared with ClickHouse builds, which is
    what preemption, job lookups and the abandoned-job reaper match on.
    """
    return f"materialize-view-{dag_id}-{node_id}-trino"


def manual_trino_workflow_id(dag_id: str) -> str:
    """A new id for a Trino run that a person starts by hand.

    Each manual run gets its own id, so manual runs of different models can overlap. The fixed
    build id of each node keeps two runs from building one model at once. The id shares the
    `execute-dag-trino-{dag_id}` prefix with the scheduled shadows, so one visibility query
    finds every Trino run of the DAG.
    """
    return f"execute-dag-trino-{dag_id}-manual-{uuid.uuid4()}"


@dataclasses.dataclass(frozen=False)
class ExecuteDAGInputs:
    """Inputs for the ExecuteDAGWorkflow.

    Attributes:
        team_id: the team ID that owns the DAG.
        dag_id: the DAG to execute.
        node_ids: optional list of specific node IDs to materialize. If not provided,
            all materializable nodes in the DAG will be processed.
        shadow: a Trino shadow of a ClickHouse run. Its failures stay in job rows and metrics,
            so it runs no data quality checks and sends no failure notifications.
        manually_triggered_by_id: the user who asked for this run, when a person did.
        trigger: what started this run, a MaterializationRunTrigger value.
        requested_at: the ISO 8601 time of the request that started this run, when its start recorded one.
    """

    team_id: int
    dag_id: str
    node_ids: list[str] | None = None
    managed_warehouse_only: bool = False
    dangerously_execute_raw_sql: bool = False
    # Old workflow payloads contain this field, so removing it would prevent replay after deployment.
    duckgres_only: bool = False
    shadow: bool = False
    manually_triggered_by_id: int | None = None
    trigger: str = MaterializationRunTrigger.UNKNOWN.value
    requested_at: str | None = None

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_ids": self.node_ids,
        }


@dataclasses.dataclass(frozen=True, kw_only=True)
class MaterializeViewWorkflowInputs:
    """Inputs for the MaterializeViewWorkflow.

    Attributes:
        team_id: The team ID that owns the node.
        dag_id: The DAG the node belongs to.
        node_id: The UUID of the Node to materialize.
        manually_triggered_by_id: The user who asked for this run, when a person did.
        trigger: What started this run, a MaterializationRunTrigger value.
        requested_at: The ISO 8601 time of the request that started this run, when its start recorded one.
    """

    team_id: int
    dag_id: str
    node_id: str
    managed_warehouse_only: bool = False
    dangerously_execute_raw_sql: bool = False
    manually_triggered_by_id: int | None = None
    skip_trino: bool = False
    trigger: str = MaterializationRunTrigger.UNKNOWN.value
    requested_at: str | None = None
    # Old workflow payloads contain this field, so removing it would prevent replay after deployment.
    duckgres_only: bool = False

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
        }
