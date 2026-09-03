"""Revoke the gateway credentials a blocklisted identity already holds.

Consent refuses a banned user a new grant, but a ban still has to reach the
credentials issued before it. This is what closes the legacy gateway, which
authenticates the `pha_` straight out of Postgres and reads nothing else.

Expired access tokens are candidates too: the row is how a still-live refresh
token is reached, and refresh mints a replacement without passing consent.
First-party access lasts 7 days against a 30-day refresh token, so selecting only
live rows leaves a three-week window where a dormant account is invisible.
"""

import uuid

from django.db.models import Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.dataclasses import frozen
from posthog.llm.wizard_blocklist import (
    GATEWAY_BEARING_SCOPES,
    blocklist_flag_defined,
    record_blocklist_outcome,
    wizard_identity_blocked,
)
from posthog.models.oauth import OAuthAccessToken, oauth_scope_tokens_expression, revoke_oauth_session
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 1000

# One tick's ceiling. Each revocation is a locked transaction plus cascading
# deletes, and a condition group with no properties matches every identity at
# once; the next tick continues the backlog.
_MAX_REVOCATIONS_PER_RUN = 200


@frozen
class SweepResult:
    """What one sweep did. Named because two bare counts swap silently."""

    blocked_users: int = 0
    revoked_sessions: int = 0
    capped: bool = False


def sweep_blocklisted_gateway_credentials() -> SweepResult:
    """Revoke every gateway-bearing session held by a blocklisted user."""
    verdicts: dict[tuple[int, str, int | None], bool] = {}
    revoked_pairs: set[tuple[int, uuid.UUID]] = set()
    blocked_user_ids: set[int] = set()

    candidates = (
        OAuthAccessToken.objects.alias(scope_tokens=oauth_scope_tokens_expression())
        .filter(scope_tokens__overlap=sorted(GATEWAY_BEARING_SCOPES), application_id__isnull=False)
        .filter(user__isnull=False)
        # An expired row is only worth reading for the refresh token hanging off it.
        # Server-minted sandbox tokens carry this scope, expire in hours, have no
        # refresh token and are kept 30 days, so admitting every expired row scans
        # that backlog for credentials a ban cannot reach.
        .filter(Q(expires__gt=timezone.now()) | Q(refresh_token__isnull=False))
        .select_related("user", "application")
        .iterator(chunk_size=_CHUNK_SIZE)
    )
    for token in candidates:
        user = token.user
        if user is None or token.application_id is None:
            continue
        # Keyed on the whole question: the verdict depends on the token's own
        # organization and team, so a user-keyed memo would answer for whichever
        # row the unordered scan read first.
        question = (user.pk, _organization_id(token), _team_id(token))
        blocked = verdicts.get(question)
        if blocked is None:
            blocked = wizard_identity_blocked(
                distinct_id=str(user.distinct_id),
                email=user.email,
                surface="revoke_sweep",
                organization_id=question[1],
                team_id=question[2],
            )
            verdicts[question] = blocked
            if blocked:
                blocked_user_ids.add(user.pk)
        if not blocked:
            continue
        # revoke_oauth_session sweeps the whole (user, application) pair, so a user
        # holding several tokens against one app is one revoke, not one per token.
        pair = (user.pk, token.application_id)
        if pair in revoked_pairs:
            continue
        revoke_oauth_session(access_token=token)
        revoked_pairs.add(pair)
        if len(revoked_pairs) >= _MAX_REVOCATIONS_PER_RUN:
            logger.warning(
                "wizard_blocklist: revocation cap reached, deferring the rest to the next run",
                revoked_sessions=len(revoked_pairs),
            )
            # A capped run has not swept the estate; the counts alone would read
            # as one that had.
            return SweepResult(blocked_users=len(blocked_user_ids), revoked_sessions=len(revoked_pairs), capped=True)

    return SweepResult(blocked_users=len(blocked_user_ids), revoked_sessions=len(revoked_pairs))


def _organization_id(token: OAuthAccessToken) -> str:
    """The organization this credential is pinned to, or "". Not the user's current
    organization, which is writable through `PATCH /api/users/@me/` and would let a
    banned account switch itself out of the match."""
    scoped = token.scoped_organizations or []
    return str(scoped[0]) if len(scoped) == 1 else ""


def _team_id(token: OAuthAccessToken) -> int | None:
    scoped = token.scoped_teams or []
    return scoped[0] if len(scoped) == 1 else None


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def revoke_blocklisted_gateway_credentials() -> None:
    if not blocklist_flag_defined():
        # Also true when the SDK lost its definitions: a 401, a quota limit or a
        # missing personal API key all reset them to empty. Recorded so a sweep
        # that checked nothing is not silence.
        record_blocklist_outcome("revoke_sweep", "unconfigured")
        logger.info("wizard_blocklist: no blocklist flag defined, skipping the sweep")
        return
    result = sweep_blocklisted_gateway_credentials()
    logger.info(
        "wizard_blocklist: sweep complete",
        blocked_users=result.blocked_users,
        revoked_sessions=result.revoked_sessions,
        capped=result.capped,
    )
