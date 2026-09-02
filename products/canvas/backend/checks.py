"""Boot-time validation of the canvas artifact delivery configuration.

A half-configured artifact origin used to fail silently: every build would
succeed and then serve ``artifact_url: null``. These system checks make a
misconfiguration fail the deploy instead. An entirely unset origin is legal —
it means artifact delivery is off (DEBUG/TEST fall back to SITE_URL).
"""

from typing import Any

from django.conf import settings
from django.core.checks import Error, register


@register("canvas")
def check_artifact_delivery_settings(app_configs: Any, **kwargs: Any) -> list[Error]:
    if settings.DEBUG or settings.TEST:
        return []
    origin = settings.CANVAS_ARTIFACT_ORIGIN
    dedicated_keys = settings.CANVAS_ARTIFACT_SIGNING_KEYS
    if not origin and not dedicated_keys:
        return []

    from products.canvas.backend.artifacts import (  # noqa: PLC0415 — Django app registry must be ready
        _artifact_signing_keys,
        _configured_artifact_host,
    )

    errors: list[Error] = []
    keys = _artifact_signing_keys()
    if not origin or not keys:
        errors.append(
            Error(
                "Canvas artifact delivery needs CANVAS_ARTIFACT_ORIGIN and a signing key from "
                "CANVAS_ARTIFACT_SIGNING_KEYS or SECRET_KEY.",
                id="canvas.E001",
            )
        )
    if origin and _configured_artifact_host() is None:
        errors.append(
            Error(
                f"CANVAS_ARTIFACT_ORIGIN ({origin!r}) must be a bare https origin with no path, "
                "query, fragment, or credentials.",
                id="canvas.E002",
            )
        )
    invalid_key_positions = [str(index + 1) for index, key in enumerate(keys) if len(key) < 32]
    if invalid_key_positions:
        errors.append(
            Error(
                "Every Canvas artifact signing key must be at least 32 characters; invalid position(s): "
                + ", ".join(invalid_key_positions),
                id="canvas.E003",
            )
        )
    return errors
