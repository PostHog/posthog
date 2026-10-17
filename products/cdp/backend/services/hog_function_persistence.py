from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from pydantic import JsonValue

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.cdp.backend.models.hog_functions.hog_function import HogFunction


def upsert_hog_function(
    payload: Mapping[str, JsonValue],
    *,
    team: Team,
    created_by: User,
    instance: HogFunction | None = None,
    managed_destination: Literal["alert", "mcp"] | None = None,
) -> HogFunction:
    from products.cdp.backend.api.hog_function import (  # noqa: PLC0415 - keeps the legacy DRF API off facade import paths
        HogFunctionSerializer,
    )

    serializer = HogFunctionSerializer(
        instance=instance,
        data=dict(payload),
        context={
            "get_team": lambda: team,
            "is_create": instance is None,
            "allow_managed_alert_destination": managed_destination == "alert",
            "allow_mcp_event_subscription": managed_destination == "mcp",
        },
    )
    serializer.is_valid(raise_exception=True)
    return cast("HogFunction", serializer.save(team=team, created_by=created_by))
