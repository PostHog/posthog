import importlib
import threading
from typing import TYPE_CHECKING

from posthog.temporal.health_checks.models import BatchDetectFn

if TYPE_CHECKING:
    from posthog.clickhouse.query_tagging import Product
    from posthog.temporal.health_checks.framework import HealthCheckRegistration

HEALTH_CHECKS: dict[str, "HealthCheckRegistration"] = {}
_DETECT_FNS: dict[str, BatchDetectFn] = {}

# Add product health check modules here to register them.
HEALTH_CHECK_MODULES = [
    "products.data_warehouse.backend.temporal.health_checks.external_data_failure",
    "products.web_analytics.backend.temporal.health_checks.no_live_events",
    "products.web_analytics.backend.temporal.health_checks.no_pageleave_events",
    "products.growth.backend.temporal.health_checks.sdk_outdated",
    "products.cdp.backend.temporal.health_checks.ingestion_warnings",
    "products.data_warehouse.backend.temporal.health_checks.materialized_view_failure",
    "products.web_analytics.backend.temporal.health_checks.scroll_depth",
    "products.web_analytics.backend.temporal.health_checks.authorized_urls",
    "products.web_analytics.backend.temporal.health_checks.reverse_proxy",
    "products.web_analytics.backend.temporal.health_checks.web_vitals",
]

_registry_loaded = False
_registry_lock = threading.Lock()


def get_detect_fn(kind: str) -> BatchDetectFn:
    fn = _DETECT_FNS.get(kind)
    if fn is None:
        raise KeyError(f"No detect function registered for kind '{kind}'")
    return fn


def get_product(kind: str) -> "Product | None":
    reg = HEALTH_CHECKS.get(kind)
    return reg.product if reg is not None else None


def ensure_registry_loaded() -> None:
    global _registry_loaded
    with _registry_lock:
        if _registry_loaded:
            return
        for module_path in HEALTH_CHECK_MODULES:
            importlib.import_module(module_path)
        _registry_loaded = True


def _reset_registry() -> None:
    global _registry_loaded
    HEALTH_CHECKS.clear()
    _DETECT_FNS.clear()
    _registry_loaded = False
