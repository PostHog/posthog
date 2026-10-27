"""Billing quota checks for business knowledge.

Quota limiting marks a team as limited once its organization runs past the free tier with no billing
limit headroom. When that happens:

- Ingestion stops: no new sources, edits, refreshes or learned sources. Existing knowledge stays
  searchable, the way session replay stops recording but keeps past recordings.
- Retrieval stops on the public API. Support replies and PostHog AI carry on without business
  knowledge context, the way subscriptions skip the AI summary but still deliver.

A failed lookup lets the work through (fails open), so a brief Redis outage never blocks a customer.
"""

import structlog

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


def _is_limited(team_id: int, resource_name: str, api_token: str | None) -> bool:
    try:
        # Imported here so the billing stack stays off the import path of every module that imports logic,
        # and inside the try so a deployment without the ee billing module fails open.
        from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited  # noqa: PLC0415

        # Quota limiting marks every team of a limited organization, so any of its teams' tokens works.
        # Callers that already hold the team pass its token and skip this query.
        if api_token is None:
            api_token = Team.objects.only("api_token").get(id=team_id).api_token
        return is_team_limited(api_token, QuotaResource(resource_name), QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
    except Exception:
        logger.warning("business_knowledge.quota_check_failed", team_id=team_id, resource=resource_name, exc_info=True)
        return False


def is_ingestion_limited(team_id: int, api_token: str | None = None) -> bool:
    return _is_limited(team_id, "business_knowledge_chunks", api_token)


def is_retrieval_limited(team_id: int, api_token: str | None = None) -> bool:
    return _is_limited(team_id, "business_knowledge_queries", api_token)
