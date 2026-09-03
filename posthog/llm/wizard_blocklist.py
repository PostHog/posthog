"""Refuse a wizard identity the abuse blocklist names.

The list lives in the flag's conditions: Django derives the match keys and passes
them as person properties, so a ban is a flag edit rather than a deploy.

Evaluation is local-only, because a gate on `/oauth/authorize` must not add an
outbound request to every OAuth grant. That makes the flag's shape part of the
contract: a cohort condition cannot be evaluated locally, and `inconclusive` is
what surfaces that rather than letting it read as "nobody is banned". A flag
outage fails open, since losing the blocklist must not refuse every wizard run.
"""

from collections.abc import Iterable

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.scopes import PRIVILEGED_SCOPES

logger = structlog.get_logger(__name__)

# Conditions read `user_uuid`, `email`, `email_root`, `email_domain`,
# `organization_id` and `team_id`. Every release condition must carry one of them:
# a group with no properties bans every wizard user rather than the ones named.
# `user_uuid` is the only key the banned account cannot change; an address can be
# swapped through `PATCH /api/users/@me/`, so an email key bans a mailbox and
# `user_uuid` bans the account.
WIZARD_BLOCKLIST_FLAG = "wizard-gateway-blocklist"

# Wider than the two privileged names: the legacy gateway authenticates a bare
# `*`, which an app with an empty ceiling is still granted verbatim.
GATEWAY_BEARING_SCOPES = frozenset(PRIVILEGED_SCOPES | {"*"})

# Gmail ignores dots in the local part, so one mailbox has many spellings.
_DOT_INSENSITIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

# One string for every surface: the wizard shows it to the user, so a ban reads
# the same whether it lands at consent, at the mint, or on a query.
WIZARD_BLOCKED_DETAIL = (
    "This account is blocked from the PostHog AI gateway for suspected abuse. "
    "Contact wizard@posthog.com if you believe this is a mistake."
)

# `allowed` is the denominator a block count needs to read as a rate.
# `unconfigured` is the state before anyone writes the flag; `inconclusive` means
# a written flag is not enforcing.
WIZARD_BLOCKLIST_CHECKS = Counter(
    "posthog_wizard_blocklist_checks_total",
    "Blocklist checks, by surface and outcome (blocked/allowed/unconfigured/inconclusive)",
    labelnames=["surface", "outcome"],
)


def blocklist_properties(
    *, email: str | None, user_uuid: str = "", organization_id: str = "", team_id: int | None = None
) -> dict[str, str]:
    """The match keys the flag's conditions read.

    Every key is always present: a condition naming a key we omitted would
    silently never match. Only `email_root` folds provider aliasing, so banning
    an `email_domain` matches what an abuse report shows.
    """
    address = (email or "").strip().lower()
    local, at, domain = address.rpartition("@")
    if not at:
        # No domain to fold or ban: an address this shape only matches literally.
        return {
            "user_uuid": user_uuid,
            "email": address,
            "email_root": address,
            "email_domain": "",
            "organization_id": organization_id,
            "team_id": _team_key(team_id),
        }
    root_local = local.split("+", 1)[0]
    root_domain = domain
    if domain in _DOT_INSENSITIVE_DOMAINS:
        root_local = root_local.replace(".", "")
        root_domain = "gmail.com"
    return {
        "user_uuid": user_uuid,
        "email": address,
        "email_root": f"{root_local}@{root_domain}",
        "email_domain": domain,
        "organization_id": organization_id,
        "team_id": _team_key(team_id),
    }


def _team_key(team_id: int | None) -> str:
    return "" if team_id is None else str(team_id)


def blocklist_flag_defined() -> bool:
    """Whether local definitions carry the flag, which is how "no ban list exists"
    is told apart from "the ban list cannot be evaluated". The SDK reports both as
    None."""
    try:
        definitions = posthoganalytics.feature_flag_definitions()
    except Exception:
        return False
    flags = definitions.get("flags", []) if isinstance(definitions, dict) else (definitions or [])
    return any(isinstance(flag, dict) and flag.get("key") == WIZARD_BLOCKLIST_FLAG for flag in flags)


def _match_contexts(organization_ids: Iterable[str], team_ids: Iterable[int]) -> list[tuple[str, int | None]]:
    """The (organization, team) pairs a credential reaches, asked one at a time.

    A credential scoped to several organizations grants all of them, so collapsing
    it to a single value would let a ban naming one of them miss.
    """
    organizations = list(dict.fromkeys(str(org) for org in organization_ids if str(org)))
    teams = list(dict.fromkeys(team_ids))
    if len(organizations) <= 1:
        organization_id = organizations[0] if organizations else ""
        return [(organization_id, team_id) for team_id in teams] or [(organization_id, None)]
    if not teams:
        return [(organization_id, None) for organization_id in organizations]
    # Which team sits in which organization is not on the credential, so ask about
    # each alone rather than inventing a pair the credential never granted.
    return [(organization_id, None) for organization_id in organizations] + [("", team_id) for team_id in teams]


def wizard_identity_blocked(
    *,
    distinct_id: str,
    email: str | None,
    surface: str,
    user_uuid: str = "",
    organization_ids: Iterable[str] = (),
    team_ids: Iterable[int] = (),
) -> bool:
    """True when the blocklist names this identity in any context the credential
    reaches; anything else answers False.

    One outcome is recorded per call, not per context, so the counter stays a count
    of identity checks.
    """
    unavailable = False
    unevaluated = False
    for organization_id, team_id in _match_contexts(organization_ids, team_ids):
        properties = blocklist_properties(
            email=email, user_uuid=user_uuid, organization_id=organization_id, team_id=team_id
        )
        try:
            blocked = posthoganalytics.feature_enabled(
                WIZARD_BLOCKLIST_FLAG,
                distinct_id,
                person_properties=properties,
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        except Exception as e:
            unavailable = True
            logger.warning("wizard_blocklist: flag unavailable", error=str(e), surface=surface)
            continue
        if blocked:
            record_blocklist_outcome(surface, "blocked")
            # The domain rather than the address, to keep mailboxes out of the logs.
            # Info rather than warn: refusals are the steady state once a ban is in place.
            logger.info(
                "wizard_blocklist: identity refused",
                surface=surface,
                email_domain=properties["email_domain"],
                organization_id=organization_id,
                team_id=team_id,
            )
            return True
        if blocked is None:
            # No verdict, which is not the same as "not banned": once the flag exists,
            # this means its conditions cannot be evaluated in-process.
            unevaluated = True
    if unavailable or (unevaluated and blocklist_flag_defined()):
        record_blocklist_outcome(surface, "inconclusive")
        if unevaluated and not unavailable:
            logger.warning("wizard_blocklist: flag could not be evaluated locally", surface=surface)
        return False
    if unevaluated:
        record_blocklist_outcome(surface, "unconfigured")
        return False
    record_blocklist_outcome(surface, "allowed")
    return False


def record_blocklist_outcome(surface: str, outcome: str) -> None:
    """Public so a caller deciding a whole run's outcome, without asking per
    identity, still reports to the same counter."""
    WIZARD_BLOCKLIST_CHECKS.labels(surface=surface, outcome=outcome).inc()
