"""
Facade for cdp.

Re-exports the HogFunction serializer cross-product API views reuse. Lazy (PEP 562) to
keep the DRF/serializer import chain off config-only import paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

_B = "products.cdp.backend."

_LAZY = {"HogFunctionSerializer": "api.hog_function"}

__all__ = [*sorted(_LAZY), "create_hog_function"]


def create_hog_function(
    *,
    team: Team,
    payload: dict[str, Any],
    created_by: User,
    allow_managed_alert_destination: bool = False,
) -> UUID:
    """Create one hog function from an already-built payload and return its id.

    Callers outside this product have no DRF request to take an acting user from, so
    `created_by` comes in directly.
    """
    # Same reason as _LAZY below: the serializer drags DRF, so it stays off this module's
    # import path.
    from products.cdp.backend.api.hog_function import HogFunctionSerializer  # noqa: PLC0415

    serializer = HogFunctionSerializer(
        data=payload,
        context={
            "get_team": lambda: team,
            "is_create": True,
            "created_by": created_by,
            "allow_managed_alert_destination": allow_managed_alert_destination,
        },
    )
    serializer.is_valid(raise_exception=True)
    hog_function = serializer.save(team=team)
    return hog_function.id


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
