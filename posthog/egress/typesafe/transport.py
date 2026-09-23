import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.typesafe.limiter import consume_typesafe_sync
from posthog.egress.typesafe.observability import typesafe_egress


class TypeSafeEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class TypeSafeClient(EgressClient):
    observability = typesafe_egress

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_typesafe_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> TypeSafeEgressBudgetExhausted:
        return TypeSafeEgressBudgetExhausted("TypeSafe egress budget exhausted", scope=scope)


_typesafe_client = TypeSafeClient()


def typesafe_request(*, api_key: str, body: dict[str, object], source: str, timeout: float) -> requests.Response:
    return _typesafe_client.request(
        "POST",
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        source=source,
        scope="default",
        priority=Priority.NORMAL,
        endpoint="/v1/systemone",
        timeout=timeout,
        allow_redirects=False,
    )
