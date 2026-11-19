from collections.abc import Callable

from products.context_layer.backend.temporal.dreaming import (
    ContextLayerBootstrapDreamWorkflow,
    ContextLayerDreamCoordinatorWorkflow,
    dispatch_dream_run,
    fetch_dream_candidates,
)

WORKFLOWS = [ContextLayerDreamCoordinatorWorkflow, ContextLayerBootstrapDreamWorkflow]
ACTIVITIES: list[Callable[..., object]] = [fetch_dream_candidates, dispatch_dream_run]
