import requests
from pydantic import JsonValue

from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.typesafe.limiter import consume_typesafe_sync
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
        return TypeSafeEgressBudgetExhausted("TypeSafe request budget exhausted; retry in a later run")


_typesafe_client = TypeSafeClient()


def typesafe_request(
    *,
    api_key: str,
    body: dict[str, JsonValue],
    source: str,
    priority: Priority = Priority.NORMAL,
) -> requests.Response:
    return _typesafe_client.request(
        "POST",
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        source=source,
        scope=scope_fingerprint(api_key),
        endpoint="/v1/systemone",
        priority=priority,
        timeout=(5.0, 30.0),
        allow_redirects=False,
    )
