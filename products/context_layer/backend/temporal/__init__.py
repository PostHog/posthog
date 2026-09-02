from products.context_layer.backend.temporal.dreaming import (
    ContextLayerBootstrapDreamWorkflow,
    ContextLayerDreamCoordinatorWorkflow,
    dispatch_dream_run,
    fetch_dream_candidates,
)

WORKFLOWS = [ContextLayerDreamCoordinatorWorkflow, ContextLayerBootstrapDreamWorkflow]
ACTIVITIES = [fetch_dream_candidates, dispatch_dream_run]
