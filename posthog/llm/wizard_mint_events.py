"""Mint-time events for the wizard's gateway path.

A refusal at the mint is the terminal denial of a run that never reaches the
gateway, so nothing downstream records it. Both events key the abuse queries
(mints per org per day, cap-hit-then-re-mint, new orgs per email root), which
is why they carry the blocklist match keys rather than only a distinct id.
"""

from typing import Any

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.llm.wizard_blocklist import blocklist_properties
from posthog.models import Team, User
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

WIZARD_MINT_DENIED_EVENT = "wizard gateway mint denied"
WIZARD_TOKEN_MINTED_EVENT = "wizard gateway token minted"

# A refusal with no resolved identity (no bearer, or the endpoint is off) is
# reported against this id with person processing disabled.
PERSONLESS_DISTINCT_ID = "wizard:gateway_token"

_MAX_PROGRAM_LENGTH = 100


def report_wizard_mint_denied(
    *,
    surface: str,
    outcome: str,
    status_code: int,
    program: object,
    product_node: str | None,
    user: User | None = None,
    team: Team | None = None,
    distinct_id: str | None = None,
    posture: str | None = None,
) -> None:
    """Report one refused mint. Never raises: the refusal is already on its way
    to the caller, and a capture failure must not replace it with a 500."""
    properties = _common_properties(
        surface=surface, program=program, product_node=product_node, user=user, team=team, posture=posture
    )
    properties.update({"outcome": outcome, "status_code": status_code})
    _capture(WIZARD_MINT_DENIED_EVENT, properties, user=user, team=team, distinct_id=distinct_id)


def report_wizard_token_minted(
    *,
    program: object,
    product_node: str,
    user: User,
    team: Team,
    cap_usd: object = None,
    posture: str | None = None,
) -> None:
    """Report one successful mint; the same keys as a denial so the two join."""
    properties = _common_properties(
        surface="gateway_token", program=program, product_node=product_node, user=user, team=team, posture=posture
    )
    properties["cap_usd"] = str(cap_usd) if cap_usd is not None else None
    _capture(WIZARD_TOKEN_MINTED_EVENT, properties, user=user, team=team)


def _common_properties(
    *,
    surface: str,
    program: object,
    product_node: str | None,
    user: User | None,
    team: Team | None,
    posture: str | None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "surface": surface,
        "program": _program_label(program),
        "product_node": product_node,
        "posture": posture,
        "posthog_region": get_instance_region(),
    }
    if user is not None:
        properties.update(
            blocklist_properties(
                email=user.email,
                user_uuid=str(user.uuid),
                organization_id=str(team.organization_id) if team is not None else "",
                team_id=team.id if team is not None else None,
            )
        )
    return properties


def _program_label(program: object) -> str:
    """The caller's program as a bounded string; a non-string is caller JSON of
    the wrong shape and carries nothing worth keying on."""
    if not isinstance(program, str):
        return ""
    return program[:_MAX_PROGRAM_LENGTH]


def _capture(
    event: str,
    properties: dict[str, Any],
    *,
    user: User | None,
    team: Team | None,
    distinct_id: str | None = None,
) -> None:
    # Bare capture, not report_user_action: a denial must not $set_once an email
    # onto a person, and four outcomes have a user but no team.
    if user is not None:
        distinct_id = str(user.distinct_id)
    if not distinct_id:
        distinct_id = PERSONLESS_DISTINCT_ID
        properties["$process_person_profile"] = False
    try:
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event,
            properties=properties,
            groups=groups(team.organization, team) if team is not None else None,
        )
    except Exception as e:
        logger.warning("wizard_mint_events: capture failed", event_name=event, error=str(e))
