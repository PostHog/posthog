import dataclasses

from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import sync_connect


@dataclasses.dataclass(frozen=True)
class TrinoModelReservationInputs:
    team_id: int
    node_id: str
    workflow_id: str


@database_sync_to_async_pool
def _reserve(inputs: TrinoModelReservationInputs) -> bool:
    # Imported here because the reservations module reads the DAG workflow's timeout, and that workflow imports this.
    from products.data_modeling.backend.logic.trino_reservations import Liveness, reserve_trino_models

    reserved, _ = reserve_trino_models(
        Liveness(sync_connect()), inputs.team_id, {inputs.node_id}, inputs.workflow_id, manual=False
    )
    return bool(reserved)


@database_sync_to_async_pool
def _release(inputs: TrinoModelReservationInputs) -> None:
    from products.data_modeling.backend.logic.trino_reservations import release_trino_reservations

    release_trino_reservations(inputs.team_id, [inputs.node_id], inputs.workflow_id)


@activity.defn
async def reserve_trino_model_activity(inputs: TrinoModelReservationInputs) -> bool:
    """Reserve a model for one scheduled Trino build. False when a live run already holds it."""
    return await _reserve(inputs)


@activity.defn
async def release_trino_model_activity(inputs: TrinoModelReservationInputs) -> None:
    await _release(inputs)
