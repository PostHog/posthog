from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.slack.observability import record_slack_api_exception, record_slack_api_response
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient


class SlackEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class SlackClient(EgressClient):
    def __init__(self, app_id: str) -> None:
        self._app_id = app_id

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return True

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

    def _record_exception(
        self,
        *,
        source: str,
        scope: str | None,
        method: str,
        url: str,
        endpoint: str | None,
    ) -> None:
        record_slack_api_exception(
            source=source,
            workspace_id=scope,
            method=method,
            endpoint=endpoint or "unknown",
        )

    def _budget_exhausted_error(self, scope: str) -> SlackEgressBudgetExhausted:
        return SlackEgressBudgetExhausted(f"Slack egress budget exhausted for workspace {scope}")


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
