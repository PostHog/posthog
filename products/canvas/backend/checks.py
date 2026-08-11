"""Boot-time validation of the canvas artifact delivery configuration.

A half-configured artifact origin used to fail silently: every build would
succeed and then serve ``artifact_url: null``. These system checks make a
misconfiguration fail the deploy instead. An entirely unset configuration is
legal — it means artifact delivery is off (DEBUG/TEST fall back to SITE_URL).
"""

from typing import Any

from django.conf import settings
from django.core.checks import Error, register


@register("canvas")
def check_artifact_delivery_settings(app_configs: Any, **kwargs: Any) -> list[Error]:
    if settings.DEBUG or settings.TEST:
        return []
    origin = settings.CANVAS_ARTIFACT_ORIGIN
    keys = settings.CANVAS_ARTIFACT_SIGNING_KEYS
    if not origin and not keys:
        return []

    from products.canvas.backend.artifacts import _configured_artifact_host  # noqa: PLC0415

    errors: list[Error] = []
    if not origin or not keys:
        errors.append(
            Error(
                "CANVAS_ARTIFACT_ORIGIN and CANVAS_ARTIFACT_SIGNING_KEYS must be set together — "
                "half-configured artifact delivery serves no artifacts.",
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
                "Every CANVAS_ARTIFACT_SIGNING_KEY must be at least 32 characters; invalid position(s): "
                + ", ".join(invalid_key_positions),
                id="canvas.E003",
            )
        )
    return errors
