from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings

import structlog
from rest_framework.exceptions import Throttled

from posthog.api.query import CONCURRENCY_LIMIT_USER_MESSAGE
from posthog.clickhouse.client.limit import (
    ConcurrencyLimitExceeded,
    app_org_concurrency_slot,
    get_api_team_rate_limiter,
)
from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method
from posthog.constants import AvailableFeature
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


def _api_key_concurrency_limit(team: Team) -> int | None:
    if not settings.EE_AVAILABLE or not settings.API_QUERIES_ENABLED:
        return None
    feature = team.organization.get_available_feature(AvailableFeature.API_QUERIES_CONCURRENCY)
    return feature.get("limit") if feature else None


@contextmanager
def query_concurrency_slots(team: Team) -> Iterator[None]:
    """Hold the slots a query runner holds, so a resource read counts against the same limits as a query."""
    is_api_key_access = is_api_key_access_method(get_query_tag_value("access_method"))
    try:
        with (
            get_api_team_rate_limiter().run(
                is_api=is_api_key_access,
                team_id=team.pk,
                limit=_api_key_concurrency_limit(team) if is_api_key_access else None,
            ),
            app_org_concurrency_slot(team),
        ):
            yield
    except ConcurrencyLimitExceeded as error:
        logger.warning("ai_trace_query_concurrency_limit_exceeded", detail=str(error))
        raise Throttled(detail=CONCURRENCY_LIMIT_USER_MESSAGE) from error
