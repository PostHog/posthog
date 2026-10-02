"""
Block sign-ups that match staff-configured rules.

The rules live in the `SIGNUP_BLOCK_RULES` instance setting, not in code, so staff can
change them at runtime and the patterns stay out of this public repository.
"""

import re
import json
import hashlib
from functools import lru_cache

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.workos_radar import SuspiciousAttemptBlocked

logger = structlog.get_logger(__name__)


@frozen
class SignupBlockRule:
    id: str
    pattern: re.Pattern[str]


@lru_cache(maxsize=8)
def _parse_rules(raw_rules: str) -> tuple[SignupBlockRule, ...]:
    # A bad setting must not stop every sign-up, so an unreadable rule is skipped.
    try:
        entries = json.loads(raw_rules or "[]")
    except json.JSONDecodeError as error:
        capture_exception(error)
        logger.exception("signup_block_rules_invalid_json")
        return ()
    if not isinstance(entries, list):
        logger.error("signup_block_rules_not_a_list")
        return ()

    rules: list[SignupBlockRule] = []
    for entry in entries:
        try:
            rules.append(SignupBlockRule(id=str(entry["id"]), pattern=re.compile(entry["pattern"])))
        except (KeyError, TypeError, re.error) as error:
            capture_exception(error)
            logger.exception("signup_block_rule_invalid", entry=entry)
    return tuple(rules)


def signup_block_subject(email: str, organization_name: str) -> str:
    """The string a rule pattern must fully match: the lowercased email, a `|`, then the organization name."""
    return f"{email.strip().lower()}|{organization_name}"


def find_signup_block_rule(email: str, organization_name: str) -> SignupBlockRule | None:
    subject = signup_block_subject(email, organization_name)
    for rule in _parse_rules(get_instance_setting("SIGNUP_BLOCK_RULES")):
        if rule.pattern.fullmatch(subject):
            return rule
    return None


def reject_blocked_signup(email: str, organization_name: str) -> None:
    """Raise `SuspiciousAttemptBlocked` when a sign-up matches a block rule."""
    rule = find_signup_block_rule(email, organization_name)
    if rule is None:
        return

    email_domain = email.rsplit("@", 1)[-1].lower()
    email_hash = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    logger.warning("signup_blocked_by_rule", rule_id=rule.id, email_domain=email_domain)
    posthoganalytics.capture(
        distinct_id=f"pre_signup_{email_hash}",
        event="signup blocked by rule",
        properties={"rule_id": rule.id, "email_domain": email_domain},
    )
    raise SuspiciousAttemptBlocked()
