"""
Facade for cdp.

Re-exports the HogFunction serializer cross-product API views reuse. Lazy (PEP 562) to
keep the DRF/serializer import chain off config-only import paths.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from posthog.cdp.flag_gated_templates import FLAG_GATED_TEMPLATE_IDS, gated_template_enabled
from posthog.models.team import Team
from posthog.models.user import User

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate

_B = "products.cdp.backend."

_LAZY = {"HogFunctionSerializer": "api.hog_function"}

__all__ = [
    *sorted(_LAZY),
    "create_hog_functions",
    "enabled_destination_templates",
    "is_hog_function_template_available",
]


def is_hog_function_template_available(template_id: str, team: Team) -> bool:
    if HogFunctionTemplate.get_template(template_id) is None:
        return False
    flag = FLAG_GATED_TEMPLATE_IDS.get(template_id)
    return flag is None or gated_template_enabled(flag, team)


def enabled_destination_templates(team_ids: Sequence[int], template_id_pattern: str) -> dict[int, list[str]]:
    """The templates of each project's enabled, live hog functions whose template id matches the pattern.

    For reading across many projects at once, such as which ones already send through another tool.
    """
    from products.cdp.backend.models.hog_functions.hog_function import (
        HogFunction,  # noqa: PLC0415 — keeps the model off the facade's import path
    )

    found: dict[int, set[str]] = {}
    rows = HogFunction.objects.filter(
        team_id__in=list(team_ids), enabled=True, deleted=False, template_id__iregex=template_id_pattern
    ).values_list("team_id", "template_id")
    for team_id, template_id in rows:
        if template_id:
            found.setdefault(team_id, set()).add(template_id)
    return {team_id: sorted(templates) for team_id, templates in found.items()}


def create_hog_functions(
    payloads: Sequence[dict[str, Any]],
    *,
    team_id: int,
    created_by_id: int,
    allow_managed_alert_destination: bool,
) -> list[UUID]:
    """Create one hog function per payload and return their ids in the order given.

    Callers outside this product have no DRF request to take an acting user from, so the
    acting user comes in as an id. The team and the acting user are resolved once for the
    whole batch, so a caller writing several functions still pays two point lookups.
    """
    # Same reason as _LAZY below: the serializer drags DRF, so it stays off this module's
    # import path.
    from products.cdp.backend.api.hog_function import HogFunctionSerializer  # noqa: PLC0415

    team = Team.objects.get(id=team_id)
    created_by = User.objects.get(id=created_by_id)
    created_ids: list[UUID] = []
    for payload in payloads:
        serializer = HogFunctionSerializer(
            data=payload,
            context={
                "get_team": lambda: team,
                "is_create": True,
                "allow_managed_alert_destination": allow_managed_alert_destination,
            },
        )
        serializer.is_valid(raise_exception=True)
        created_ids.append(serializer.save(team=team, created_by=created_by).id)
    return created_ids


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
