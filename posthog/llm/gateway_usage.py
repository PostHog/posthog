import re
from decimal import Decimal

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_USD_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?\Z")


@frozen
class GatewayRequestCost:
    model: str
    provider: str
    cost_microusd: int


async def fetch_gateway_cost(request_id: str, *, base_url: str, api_key: str) -> GatewayRequestCost | None:
    import aiohttp  # noqa: PLC0415 - keeps aiohttp off Django's startup path

    base_url = base_url.rstrip("/").removesuffix("/v1")
    if not base_url or not api_key or not _REQUEST_ID.fullmatch(request_id):
        return None
    try:
        async with (
            aiohttp.ClientSession(trust_env=True) as session,
            session.get(
                f"{base_url}/v1/usage/{request_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=15, connect=2, sock_read=3),
                allow_redirects=False,
            ) as response,
        ):
            if response.status != 200:
                logger.warning("gateway_usage.cost_pending", status_code=response.status)
                return None
            body = await response.json()
        if not isinstance(body, dict) or body.get("request_id") != request_id:
            return None
        amount = body.get("cost_usd")
        model, provider = body.get("model") or "unknown", body.get("provider") or "unknown"
        if (
            not isinstance(amount, str)
            or not _USD_AMOUNT.fullmatch(amount)
            or not isinstance(model, str)
            or len(model) > 255
            or not isinstance(provider, str)
            or len(provider) > 255
        ):
            return None
        return GatewayRequestCost(model=model, provider=provider, cost_microusd=int(Decimal(amount) * 1_000_000))
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        logger.warning("gateway_usage.lookup_failed")
        return None
