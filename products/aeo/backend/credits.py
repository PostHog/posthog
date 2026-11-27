import structlog

from posthog.llm.billing import BILLABLE_AI_PRODUCTS
from posthog.models.team import Team

from products.aeo.backend.engines import AI_VISIBILITY_AI_PRODUCT
from products.aeo.backend.facade.contracts import OUT_OF_AI_CREDITS_MESSAGE, OutOfAICreditsError

logger = structlog.get_logger(__name__)


def ai_visibility_billable() -> bool:
    return AI_VISIBILITY_AI_PRODUCT in BILLABLE_AI_PRODUCTS


def out_of_ai_credits(team: Team) -> bool:
    return ai_visibility_billable() and _over_ai_credit_budget(team.id, team.api_token)


def raise_if_out_of_ai_credits(team_id: int) -> None:
    if not ai_visibility_billable():
        return
    api_token = Team.objects.values_list("api_token", flat=True).get(id=team_id)
    if _over_ai_credit_budget(team_id, api_token):
        raise OutOfAICreditsError(OUT_OF_AI_CREDITS_MESSAGE)


def _over_ai_credit_budget(team_id: int, api_token: str) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the AEO import path
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(api_token)
    except Exception:
        logger.warning("aeo_ai_credit_check_failed", team_id=team_id, exc_info=True)
        return False
