from datetime import timedelta
from enum import Enum
from typing import List, Mapping

from django.utils import timezone

from posthog.cache_utils import cache_for
from posthog.redis import get_client

RATE_LIMITER_CACHE_KEY = "@posthog/quota-limits/"


class QuotaResource(Enum):
    EVENTS = "events"
    RECORDINGS = "recordings"


def replace_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int]) -> None:
    pipe = get_client().pipeline()
    pipe.delete(f"{RATE_LIMITER_CACHE_KEY}{resource.value}")
    if tokens:
        pipe.zadd(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


@cache_for(timedelta(seconds=30), background_refresh=True)
def list_limited_team_tokens(resource: QuotaResource) -> List[str]:
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]
