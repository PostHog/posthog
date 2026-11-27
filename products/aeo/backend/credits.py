import structlog

from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.aeo.backend.facade.contracts import (
    AI_VISIBILITY_BILLING_FLAG,
    OUT_OF_AI_CREDITS_MESSAGE,
    OutOfAICreditsError,
)

logger = structlog.get_logger(__name__)

_BILLING_FIELDS = ("uuid", "organization_id", "api_token")


def ai_visibility_billable(team: Team) -> bool:
    return feature_enabled_or_false(
        AI_VISIBILITY_BILLING_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


def ai_visibility_billable_for_team(team_id: int) -> bool:
    return ai_visibility_billable(Team.objects.only(*_BILLING_FIELDS).get(id=team_id))


def out_of_ai_credits(team: Team) -> bool:
    return ai_visibility_billable(team) and _over_ai_credit_budget(team.id, team.api_token)


def raise_if_out_of_ai_credits(team_id: int) -> None:
    if out_of_ai_credits(Team.objects.only(*_BILLING_FIELDS).get(id=team_id)):
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
