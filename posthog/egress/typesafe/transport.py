from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.typesafe.limiter import consume_typesafe_sync, typesafe_account_id
from posthog.egress.typesafe.observability import typesafe_egress


class TypeSafeEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class TypeSafeClient(EgressClient):
    observability = typesafe_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_typesafe_sync(scope, priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> TypeSafeEgressBudgetExhausted:
        return TypeSafeEgressBudgetExhausted("TypeSafe egress budget exhausted; retry later")


_typesafe_client = TypeSafeClient()


def typesafe_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.BATCH,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _typesafe_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=typesafe_account_id(api_key),
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
