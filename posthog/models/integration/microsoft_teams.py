"""Microsoft Teams integration."""

from typing import Any

import requests
import structlog
from rest_framework.exceptions import ValidationError

from . import model

logger = structlog.get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
# Graph pages at 100 items or fewer, so this cap allows a large tenant and still stops a runaway loop.
MAX_GRAPH_PAGES = 20


class MicrosoftTeamsIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "microsoft-teams":
            raise Exception("MicrosoftTeamsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def list_teams(self) -> list[dict[str, str]]:
        teams = self._get_all("/me/joinedTeams")
        return [{"id": t["id"], "name": t["displayName"]} for t in teams if t.get("id") and t.get("displayName")]

    def list_channels(self, team_id: str) -> list[dict[str, str]]:
        channels = self._get_all(f"/teams/{team_id}/channels")
        return [
            {"id": c["id"], "name": c["displayName"], "membership_type": c.get("membershipType") or "standard"}
            for c in channels
            if c.get("id") and c.get("displayName")
        ]

    def _get_all(self, path: str) -> list[dict[str, Any]]:
        access_token = self.integration.sensitive_config["access_token"]
        url: str | None = f"{GRAPH_API_BASE}{path}"
        items: list[dict[str, Any]] = []

        for _ in range(MAX_GRAPH_PAGES):
            if not url:
                break
            response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
            if response.status_code != 200:
                logger.warning(
                    "microsoft_teams_graph_request_failed",
                    integration_id=self.integration.id,
                    status=response.status_code,
                )
                raise ValidationError(f"Microsoft Teams returned an error: {response.status_code}")
            body = response.json()
            items.extend(body.get("value", []))
            next_link = body.get("@odata.nextLink")
            # Only follow links back to Graph so the access token never goes to another host.
            url = next_link if isinstance(next_link, str) and next_link.startswith(f"{GRAPH_API_BASE}/") else None

        return items
