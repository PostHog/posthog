from products.context_layer.backend.temporal.dreaming import (
    ContextLayerDreamCoordinatorWorkflow,
    dispatch_dream_run,
    fetch_dream_candidates,
)

WORKFLOWS = [ContextLayerDreamCoordinatorWorkflow]
ACTIVITIES = [fetch_dream_candidates, dispatch_dream_run]
