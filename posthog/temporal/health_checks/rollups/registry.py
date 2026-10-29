import importlib
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.temporal.health_checks.rollups.framework import DailyRollup

DAILY_ROLLUPS: dict[str, type["DailyRollup"]] = {}

DAILY_ROLLUP_MODULES = [
    "products.growth.backend.temporal.rollups.sdk_versions",
    "products.web_analytics.backend.temporal.rollups.events_health",
    "products.web_analytics.backend.temporal.rollups.host_proxy",
]

_registry_loaded = False
_registry_lock = threading.Lock()


def ensure_rollups_loaded() -> None:
    global _registry_loaded
    with _registry_lock:
        if _registry_loaded:
            return
        for module_path in DAILY_ROLLUP_MODULES:
            importlib.import_module(module_path)
        _registry_loaded = True


def get_rollup(table: str) -> type["DailyRollup"]:
    ensure_rollups_loaded()
    rollup = DAILY_ROLLUPS.get(table)
    if rollup is None:
        raise KeyError(f"No daily rollup registered for table '{table}'")
    return rollup


def all_rollup_tables() -> list[str]:
    ensure_rollups_loaded()
    return sorted(DAILY_ROLLUPS)
