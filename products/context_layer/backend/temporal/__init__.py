from typing import TYPE_CHECKING

from products.context_layer.backend.temporal.dreaming import (
    ContextLayerBootstrapDreamWorkflow,
    ContextLayerDreamCoordinatorWorkflow,
    dispatch_dream_run,
    fetch_dream_candidates,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [ContextLayerDreamCoordinatorWorkflow, ContextLayerBootstrapDreamWorkflow]
ACTIVITIES: list[ActivityDefinition] = [fetch_dream_candidates, dispatch_dream_run]
