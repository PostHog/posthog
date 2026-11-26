from datetime import timedelta
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.session.dbsc.cookies import CookieCheck
from posthog.session.dbsc.rollout import Mode

# Requests the browser sent before it stored the cookie from /dbsc/start still arrive after the binding commits.
FRESH_BINDING_GRACE = timedelta(seconds=60)


class Action(StrEnum):
    ALLOW = "allow"
    RECORD = "record"
    # Send a navigation back through our own origin, so the browser refreshes the bound cookie first.
    BOUNCE = "bounce"
    # Answer without data and keep the session, because the browser could not have refreshed.
    REJECT = "reject"
    RETRY_LATER = "retry_later"
    END_SESSION = "end_session"


@frozen
class BoundRequest:
    check: CookieCheck
    mode: Mode
    binding_age: timedelta
    cross_site: bool
    navigation: bool
    bounced: bool
    refresh_skipped: bool
    challenge_store_up: bool


def decide(request: BoundRequest) -> Action:
    if request.check == CookieCheck.VALID or request.mode == Mode.OFF:
        return Action.ALLOW
    if request.check in (CookieCheck.MISSING, CookieCheck.WRONG_SESSION) and request.binding_age < FRESH_BINDING_GRACE:
        return Action.ALLOW
    if request.mode == Mode.SHADOW:
        return Action.RECORD
    # The browser refreshes only for requests our own origin starts (DBSC draft 8.3). Neither answer carries data.
    if request.cross_site and not request.navigation:
        return Action.REJECT
    if request.cross_site and not request.bounced:
        return Action.BOUNCE
    # A browser skips the refresh when our refresh endpoint fails, which says nothing about the device.
    if request.refresh_skipped and not request.challenge_store_up:
        return Action.RETRY_LATER
    return Action.END_SESSION
