from typing import Any

import requests

from posthog.egress.slack.observability import record_slack_api_response, slack_egress
from posthog.egress.transport.transport import RecordedEgressClient


class SlackClient(RecordedEgressClient):
    """Recorded, never gated. Slack applies its limits per method, workspace and app, and returns no
    remaining-budget headers, so there is no single budget to draw from. Callers own reactive retries."""

    observability = slack_egress

    def __init__(self, app_id: str) -> None:
        self._app_id = app_id

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _record_response(
        self,
        response: requests.Response,
        *,
        source: str,
        scope: str | None,
        method: str,
        endpoint: str | None,
    ) -> None:
        record_slack_api_response(
            response,
            source=source,
            workspace_id=scope,
            app_id=self._app_id,
            method=method,
            endpoint=endpoint or "unknown",
        )


def slack_request(
    method: str,
    url: str,
    *,
    source: str,
    endpoint: str,
    workspace_id: str | None = None,
    app_id: str = "unknown",
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    return SlackClient(app_id).request(
        method,
        url,
        source=source,
        scope=workspace_id or None,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
