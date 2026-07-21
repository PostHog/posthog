"""Gated, recorded transport for calls to the Vapi API."""

import hashlib
from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.vapi.limiter import consume_vapi_api_sync
from posthog.egress.vapi.observability import record_vapi_api_exception, record_vapi_api_response


class VapiEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class VapiClient(EgressClient):
    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_vapi_api_sync(scope, priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_vapi_api_response(
            response,
            source=source,
            scope=scope or "",
            method=method,
            endpoint=endpoint or "unknown",
        )

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_vapi_api_exception(
            source=source,
            scope=scope or "",
            method=method,
            endpoint=endpoint or "unknown",
            url=url,
        )

    def _budget_exhausted_error(self, scope: str) -> VapiEgressBudgetExhausted:
        return VapiEgressBudgetExhausted("Vapi egress budget exhausted")


_vapi_client = VapiClient()


def vapi_request(
    method: str,
    url: str,
    *,
    api_token: str,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    scope = hashlib.sha256(api_token.encode()).hexdigest()[:16]
    return _vapi_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_token}"},
        scope=scope,
        priority=Priority.CRITICAL,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
