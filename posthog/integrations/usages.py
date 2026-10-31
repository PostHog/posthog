"""The registry of the products that report which PostHog objects use an integration row.

A product reports its usages from `products/<product>/backend/integration_usages.py`, with a function
`integration_usages(team_id: int, integration_id: int) -> Iterable[IntegrationUsage]`. The SDK finds
these modules on the first call, so no core module has to import a product. Code outside a product
calls `register_usage_provider` instead.
"""

import threading
from collections.abc import Callable, Iterable

from posthog.integrations.contracts import IntegrationUsage
from posthog.products import load_product_modules

UsageProvider = Callable[[int, int], Iterable[IntegrationUsage]]

PRODUCT_MODULE = "integration_usages"
PRODUCT_FUNCTION = "integration_usages"

# Reentrant: a provider module can call `register_usage_provider` while `_providers` imports it.
_lock = threading.RLock()
_registered: list[UsageProvider] = []
_product_providers: list[UsageProvider] | None = None


def register_usage_provider(provider: UsageProvider) -> None:
    with _lock:
        if provider not in _registered:
            _registered.append(provider)


def _providers() -> list[UsageProvider]:
    global _product_providers
    with _lock:
        if _product_providers is None:
            _product_providers = [getattr(module, PRODUCT_FUNCTION) for module in load_product_modules(PRODUCT_MODULE)]
        return [*_product_providers, *_registered]


def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]:
    usages = [usage for provider in _providers() for usage in provider(team_id, integration_id)]
    return sorted(usages, key=lambda usage: (usage.type, usage.name, usage.id))
