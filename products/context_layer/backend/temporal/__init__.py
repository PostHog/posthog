from posthog.temporal.common.registration import ActivityDefinition

from products.context_layer.backend.temporal.dreaming import (
    ContextLayerBootstrapDreamWorkflow,
    ContextLayerDreamCoordinatorWorkflow,
    dispatch_dream_run,
    fetch_dream_candidates,
)

WORKFLOWS = [ContextLayerDreamCoordinatorWorkflow, ContextLayerBootstrapDreamWorkflow]
ACTIVITIES: list[ActivityDefinition] = [fetch_dream_candidates, dispatch_dream_run]
