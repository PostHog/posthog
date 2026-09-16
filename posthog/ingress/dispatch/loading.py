"""Builds the registry on the first delivery, then keeps it for the process.

Eager building would drag every product's webhook module onto the `django.setup()` import
path, which `posthog/test/repo_invariants/test_startup_import_budget.py` exists to keep
clear -- a shell, a migrate and every Celery worker would pay for it.
"""

from collections.abc import Sequence
from functools import lru_cache

from posthog.ingress.contracts import WebhookConsumer
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.providers import core_consumers, provider_specs
from posthog.products import load_product_modules

PRODUCT_CONSUMER_MODULE = "webhook_consumers"
PRODUCT_CONSUMER_ATTRIBUTE = "WEBHOOK_CONSUMERS"


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
        consumers=[*core_consumers(), *product_consumers()],
    )


def reset_consumer_registry() -> None:
    """Drop the cached registry. For tests that register their own consumers."""
    get_consumer_registry.cache_clear()


def get_dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher(get_consumer_registry())
