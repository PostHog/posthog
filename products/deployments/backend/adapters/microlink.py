"""Screenshot adapter boundary (microlink.io for v1).

Build/Infra stream owns the real implementation. We declare the Protocol
plus a Null stub for tests.

Screenshot capture is best-effort: a failure surfaces as a
`preview_capture_failed` DeploymentEvent row but never rolls back the
`ready` transition.
"""

from __future__ import annotations

from importlib import import_module
from typing import Protocol

from django.conf import settings


class ScreenshotAdapter(Protocol):
    """Capture a screenshot of the given URL.

    Returns the image URL on success, or None when capture failed (rate
    limit, timeout, page-load error). Callers must tolerate None.
    """

    def capture(self, *, url: str) -> str | None: ...


class NullScreenshotAdapter:
    """Stub used in tests. Returns None to mirror the failure path so
    callers exercise the `preview_capture_failed` event-emission code."""

    def capture(self, *, url: str) -> str | None:
        return None


def get_screenshot_adapter() -> ScreenshotAdapter:
    path = getattr(settings, "DEPLOYMENTS_SCREENSHOT_ADAPTER", None)
    if not path:
        return NullScreenshotAdapter()
    module_path, class_name = path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)()
