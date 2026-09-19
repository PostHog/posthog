from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from posthog.egress.cloudflare_ai.limiter import acquire_cloudflare_ai
from posthog.egress.cloudflare_ai.observability import cloudflare_ai_egress
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import AsyncEgressClient, EgressBudgetExhausted


class CloudflareAIEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class CloudflareAIClient(AsyncEgressClient):
    observability = cloudflare_ai_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return await acquire_cloudflare_ai(scope, priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> CloudflareAIEgressBudgetExhausted:
        return CloudflareAIEgressBudgetExhausted("Cloudflare AI shadow budget exhausted")


_client = CloudflareAIClient()


async def cloudflare_ai_request(
    session: aiohttp.ClientSession,
    *,
    account_id: str,
    api_token: str,
    source: str,
    payload: dict[str, object],
) -> aiohttp.ClientResponse:
    return await _client.request(
        session,
        "POST",
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run",
        scope=account_id,
        source=source,
        priority=Priority.BATCH,
        endpoint="/ai/run",
        headers={"Authorization": f"Bearer {api_token}"},
        json=payload,
    )
