"""Builds the registry on the first delivery, then keeps it for the process.

Eager building would drag every product's webhook module onto the `django.setup()` import
path, which `posthog/test/repo_invariants/test_startup_import_budget.py` exists to keep
clear -- a shell, a migrate and every Celery worker would pay for it.
"""

import importlib
from collections.abc import Sequence
from functools import lru_cache

from posthog.ingress.contracts import WebhookConsumer
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.providers import core_consumers, provider_specs
from posthog.products import load_product_modules

PRODUCT_CONSUMER_MODULE = "webhook_consumers"
PRODUCT_CONSUMER_ATTRIBUTE = "WEBHOOK_CONSUMERS"

# `ee/` is not a product, so `load_product_modules` never finds it. The modules it declares
# consumers in are named here instead, and a build without `ee/` simply has none of them.
NON_PRODUCT_CONSUMER_MODULES = ("ee.api.vercel.webhook_consumers",)


def non_product_consumers() -> list[WebhookConsumer]:
    """Consumers declared outside `products/`, by a tree core knows by name."""
    consumers: list[WebhookConsumer] = []
    for module_name in NON_PRODUCT_CONSUMER_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            # Only the tree being absent is a reason to skip. A broken import inside the module
            # raises the same class, and swallowing it would deregister the consumer in silence.
            if error.name is not None and (module_name == error.name or module_name.startswith(f"{error.name}.")):
                continue
            raise
        declared: Sequence[WebhookConsumer] = getattr(module, PRODUCT_CONSUMER_ATTRIBUTE, ())
        consumers.extend(declared)
    return consumers


def product_consumers() -> list[WebhookConsumer]:
    """Consumers declared by `products/<x>/backend/webhook_consumers.py`."""
    consumers: list[WebhookConsumer] = []
    for module in load_product_modules(PRODUCT_CONSUMER_MODULE):
        declared: Sequence[WebhookConsumer] = getattr(module, PRODUCT_CONSUMER_ATTRIBUTE, ())
        consumers.extend(declared)
    return consumers


@lru_cache(maxsize=1)
def get_consumer_registry() -> ConsumerRegistry:
    return ConsumerRegistry(
        providers=provider_specs(),
        consumers=[*core_consumers(), *non_product_consumers(), *product_consumers()],
    )


def reset_consumer_registry() -> None:
    """Drop the cached registry. For tests that register their own consumers."""
    get_consumer_registry.cache_clear()


def get_dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher(get_consumer_registry())
