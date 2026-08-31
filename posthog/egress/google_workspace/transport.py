from typing import Any

import requests

from posthog.egress.google_workspace.limiter import consume_google_workspace_sync
from posthog.egress.google_workspace.observability import (
    record_google_workspace_api_exception,
    record_google_workspace_api_response,
)
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient


class GoogleWorkspaceEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class GoogleWorkspaceClient(EgressClient):
    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_google_workspace_sync(scope, priority=priority, source=source)

    def _record_response(
        self,
        response: requests.Response,
        *,
        source: str,
        scope: str | None,
        method: str,
        endpoint: str | None,
    ) -> None:
        record_google_workspace_api_response(
            response,
            source=source,
            account_id=scope or "",
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
        record_google_workspace_api_exception(
            source=source,
            account_id=scope or "",
            method=method,
            endpoint=endpoint or "unknown",
            url=url,
        )

    def _budget_exhausted_error(self, scope: str) -> GoogleWorkspaceEgressBudgetExhausted:
        return GoogleWorkspaceEgressBudgetExhausted("Google Workspace egress budget exhausted")


_google_workspace_client = GoogleWorkspaceClient()


def google_workspace_request(
    method: str,
    url: str,
    *,
    access_token: str,
    account_id: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.BATCH,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _google_workspace_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {access_token}"},
        scope=account_id,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
