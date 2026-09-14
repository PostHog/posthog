from asgiref.sync import sync_to_async
from temporalio import activity

from ...facade.contracts import MATERIALIZATION_GATE_ACTIVITY_NAME
from ...logic.triggers import materialization_checks_needed
from ..contracts import MaterializationGateInputs


@activity.defn(name=MATERIALIZATION_GATE_ACTIVITY_NAME)
async def materialization_gate_activity(inputs: MaterializationGateInputs) -> bool:
    """Whether the DAG workflow should start a suite at all.

    Lives on the activity side because the answer needs the feature flag and the database, which a
    workflow may not touch. Asking before the start keeps a flag-disabled org from paying for a
    child workflow and an empty suite row on every materialization.
    """
    return await sync_to_async(materialization_checks_needed)(inputs.team_id, inputs.node_ids)
