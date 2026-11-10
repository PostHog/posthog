"""The model behind a resource kind, for a kind whose model lives in a sealed product.

A sealed product names its model from its own `AppConfig.ready()`, so the visitors here never import
the product's internals. This module stays light: products import it while Django sets up.
"""

from django.db import models

from posthog.models.resource_transfer.types import ResourceKind

_MODELS: dict[ResourceKind, type[models.Model]] = {}


def register_model(kind: ResourceKind, model: type[models.Model]) -> None:
    _MODELS[kind] = model


def registered_model(kind: ResourceKind) -> type[models.Model]:
    try:
        return _MODELS[kind]
    except KeyError:
        raise LookupError(f"No model is registered for the resource kind {kind}") from None
