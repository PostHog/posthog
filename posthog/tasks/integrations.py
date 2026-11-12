from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

import structlog
from celery import Task, shared_task

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.integrations import CrossTeamFilter, IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import (
    FirebaseIntegration,
    GitHubIntegration,
    GoogleCloudIntegration,
    OauthIntegration,
    refresh_backoff_active,
)
from posthog.models.integration.email import lock_sender_domain, lock_sender_if_unverified
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.facade.api import delete_ses_identity, remove_ses_tenant_associations

logger = structlog.get_logger(__name__)

GITHUB_BRANCH_REFRESH_RETRY_SECONDS = 5 * 60


# Resend is excluded: its refresh token is single-use and rotates on every refresh, with
# reuse-detection that revokes the whole grant if a rotated token is spent twice. Resend
# refreshes are minted on demand under a Postgres row lock by the sync path
# (resolve_resend_oauth_token). This unlocked periodic sweep would race that path and
# double-spend the rotating token, so it must not refresh Resend.
# The Meta kinds are excluded because their grants carry no refresh token: a long-lived token is
# re-exchanged on use by `MetaGraphIntegration.refresh_access_token` rather than by this sweep.
SWEEP_EXCLUDED_KINDS = frozenset({"meta-ads", "instagram", "resend"})


def _refresh_due(
    integration: IntegrationRecord,
    adapter: OauthIntegration | GoogleCloudIntegration | GitHubIntegration | FirebaseIntegration,
) -> bool:
    return not refresh_backoff_active(integration) and adapter.access_token_expired()


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def refresh_integrations() -> int:
    oauth_kinds = sorted(set(OauthIntegration.supported_kinds) - SWEEP_EXCLUDED_KINDS)
    for integration in IntegrationManager.kinds(*oauth_kinds, auth_types="any").list_across_teams(CrossTeamFilter()):
        if _refresh_due(integration, OauthIntegration(integration)):
            refresh_integration.delay(integration.id, integration.team_id)

    for integration in IntegrationManager.kinds(
        *GoogleCloudIntegration.supported_kinds, auth_types="any"
    ).list_across_teams(CrossTeamFilter()):
        if _refresh_due(integration, GoogleCloudIntegration(integration)):
            refresh_integration.delay(integration.id, integration.team_id)

    for integration in IntegrationManager.github.any.list_across_teams(CrossTeamFilter()):
        github_integration = GitHubIntegration(
            integration, source="integration_token_refresh", priority=Priority.CRITICAL
        )
        if _refresh_due(integration, github_integration):
            refresh_integration.delay(integration.id, integration.team_id)

    for integration in IntegrationManager.firebase.any.list_across_teams(CrossTeamFilter()):
        if _refresh_due(integration, FirebaseIntegration(integration)):
            refresh_integration.delay(integration.id, integration.team_id)

    return 0


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def refresh_integration(id: int, team_id: int | None = None) -> int:
    # A task that a sweep enqueued before the team id existed has no team to read in. The next
    # sweep enqueues the refresh again.
    if team_id is None:
        return 0

    try:
        integration = IntegrationManager.any.get(team_id, id)
    except IntegrationNotFound:
        return 0

    # Re-check backoff against the just-loaded row: a failure recorded after this task was
    # enqueued must not be retried ahead of its scheduled next attempt.
    if refresh_backoff_active(integration):
        return 0

    # Re-check freshness against the just-loaded row before minting. Under an INTEGRATIONS queue
    # backlog several duplicate refreshes can pile up for the same row; the first mints a fresh token
    # and this keeps the rest from re-minting one that's already valid.
    # Resend is deliberately not refreshed here (see SWEEP_EXCLUDED_KINDS): its rotating single-use
    # refresh token must only ever be spent under the sync path's row lock. Skip it even if an
    # in-flight task from before this guard was deployed still targets a Resend row.
    if integration.kind == "resend":
        return 0

    if integration.kind in OauthIntegration.supported_kinds:
        # The SDK locks the row and checks the expiry again under the lock.
        try:
            getattr(IntegrationManager, integration.kind.replace("-", "_")).oauth.refresh_access_token(team_id, id)
        except IntegrationNotFound:
            # The row has another auth type, such as a static token, so it has nothing to refresh.
            return 0
    elif integration.kind in GoogleCloudIntegration.supported_kinds:
        gcloud_integration = GoogleCloudIntegration(integration)
        if gcloud_integration.access_token_expired():
            gcloud_integration.refresh_access_token()
    elif integration.kind == "github":
        github_integration = GitHubIntegration(
            integration, source="integration_token_refresh", priority=Priority.CRITICAL
        )
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()
    elif integration.kind == "firebase":
        firebase_integration = FirebaseIntegration(integration)
        if firebase_integration.access_token_expired():
            firebase_integration.refresh_access_token()

    return 0


def _domain_has_sender(domain: str, *, team_id: int | None = None) -> bool:
    team_ids = (team_id,) if team_id is not None else None
    return bool(
        IntegrationManager.email.any.list_across_teams(
            CrossTeamFilter(team_ids=team_ids, where={"domain": domain}, limit=1)
        )
    )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.INTEGRATIONS.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@skip_team_scope_audit
def delete_ses_identity_if_unused(domain: str, team_id: int | None = None) -> None:
    # Under the domain lock, a sender added at the same time either commits before this check and keeps the
    # identity, or waits until the identity is gone and creates it again.
    with transaction.atomic():
        with connection.cursor() as cursor:
            lock_sender_domain(cursor, domain)
        if not _domain_has_sender(domain):
            delete_ses_identity(domain)
        elif team_id is not None and not _domain_has_sender(domain, team_id=team_id):
            # The identity stays for the other projects. A link to a project that no longer sends from the domain
            # would look like another organization's claim when someone else adds the domain.
            remove_ses_tenant_associations(domain, team_ids=[team_id])


# A sender that never verifies keeps the identity of its domain at the email provider, and the provider caps
# identities per region for all customers together.
UNVERIFIED_EMAIL_SENDER_LIFETIME = timedelta(days=14)
# Each expired sender can queue one SES DeleteIdentity call, which SES accepts once per second per account, so a
# backlog drains over several hourly runs instead of one burst that exhausts the cleanup task's retries.
EXPIRED_EMAIL_SENDERS_PER_RUN = 10


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def expire_unverified_email_senders() -> None:
    cutoff = timezone.now() - UNVERIFIED_EMAIL_SENDER_LIFETIME
    candidates = IntegrationManager.email.any.list_across_teams(CrossTeamFilter(where={"verified": False}))
    expired = 0
    for sender in candidates:
        if expired >= EXPIRED_EMAIL_SENDERS_PER_RUN:
            break
        if sender.created_at >= cutoff:
            continue
        with transaction.atomic():
            if not lock_sender_if_unverified(sender):
                continue
            # An unverified sender cannot send, so a workflow that still names it loses nothing it had.
            IntegrationManager.email.any.delete(sender.team_id, sender.id, ignore_usages=True)
        expired += 1
    logger.info("expired_unverified_email_senders", count=expired)


@shared_task(ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value)
@skip_team_scope_audit
def push_vercel_secrets(team_id: int) -> None:
    from posthog.models.team import Team

    from ee.vercel.integration import VercelIntegration

    team = Team.objects.get(id=team_id)
    VercelIntegration.push_secrets_to_vercel(team)


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, max_retries=5)
@skip_team_scope_audit
def refresh_github_branch_cache(
    self: Task, integration_id: str, repo: str, is_user_integration: bool, lock_token: str, team_id: int | None = None
) -> None:
    """Refresh one repository's cached branch list for the branch picker, on the batch lane."""
    github: GitHubIntegrationBase
    if is_user_integration:
        user_integration = UserIntegration.objects.filter(id=integration_id).first()
        if user_integration is None:
            return
        github = UserGitHubIntegration(user_integration, source="github_branch_picker", priority=Priority.BATCH)
    else:
        if team_id is None:
            # Queued before the team id was added to the task arguments: the row cannot be read by id alone.
            logger.warning("refresh_github_branch_cache_skipped_without_team_id", integration_id=integration_id)
            return
        try:
            integration = IntegrationManager.github.any.get(team_id, int(integration_id))
        except IntegrationNotFound:
            return
        github = GitHubIntegration(integration, source="github_branch_picker", priority=Priority.BATCH)
    try:
        github.refresh_branch_cache(repo, lock_token)
    except GitHubEgressBudgetExhausted as error:
        if self.request.retries < self.max_retries:
            # The lock stays held, so picker views do not queue a second refresh while this one waits.
            raise self.retry(exc=error, countdown=GITHUB_BRANCH_REFRESH_RETRY_SECONDS)
        github.release_branch_refresh_lock(repo, lock_token)
        raise
    except Exception:
        github.release_branch_refresh_lock(repo, lock_token)
        raise
    github.release_branch_refresh_lock(repo, lock_token)
