"""Opens, starts and settles the review a self-registered CIMD provisioning partner goes through.

A partner under review has its provisioning config written but left inactive, so every partner
endpoint refuses it the way it refuses a deactivated partner. Accepting turns it on. Rejecting
sets the ``disabled`` kill switch, which re-registering cannot clear, and revokes the app's
sessions. Staff can reverse either verdict later, and the review keeps each change in its run log.
The pipeline that reaches the verdict is ``posthog/temporal/cimd_provisioning_review/``.
"""

import asyncio
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics
from celery import shared_task

from posthog.api.oauth.provisioning_review_slack import queue_review_slack_thread
from posthog.cloud_utils import is_cloud
from posthog.email import EMAIL_TASK_KWARGS, EmailMessage, get_email_team_and_org_context, is_email_available
from posthog.helpers.email_utils import sanitize_display_name
from posthog.llm.system_one_client import system_one_configured
from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    PartnerProvisioningStatus,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.models.organization import OrganizationMembership
from posthog.scoping_audit import skip_team_scope_audit
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

REVIEW_DISPATCH_TIMEOUT_SECONDS = 5
REVIEW_DISPATCH_MAX_RETRIES = 8
# A partner polls the registration endpoint while it waits, and every poll asks for the review to
# be running. Inside this window that request costs no Temporal round trip.
REVIEW_DISPATCH_DEDUP_SECONDS = 60
ORGANIZATION_LINK_REQUIRED_MESSAGE = (
    "Link this client to a PostHog organization before it can provision. An organization admin creates a CIMD "
    "verification token in organization settings, and you publish it in your client metadata document, then register "
    "again."
)
# Retries append to the log, so it is capped to keep a review that failed for hours readable.
MAX_RUN_LOG_ENTRIES = 200


def review_required() -> bool:
    """Self-hosted instances have no System One server, so a review there could never finish.
    Their partners keep the self-serve behavior of being active as soon as they register.

    Cloud always reviews, so a missing or broken gateway setting sends every partner to staff
    instead of letting them in unreviewed.
    """
    return is_cloud() or system_one_configured()


def application_console_url(application_id: object) -> str:
    """The app's page in PostHog Admin, where staff read its review and decide."""
    return f"{settings.SITE_URL}/admin/console/oauth-applications/{application_id}/"


def _log_entry(step: str, message: str, *, level: str = "info", **details: Any) -> dict[str, Any]:
    return {"at": timezone.now().isoformat(), "step": step, "level": level, "message": message, **details}


def open_review(
    app: OAuthApplication, *, domain: str, metadata_document: Mapping[str, Any] | None = None
) -> CIMDProvisioningReview:
    """Create the pending review for an app that is being promoted. Call inside the promotion's
    transaction, and start the workflow once it commits."""
    review, _ = CIMDProvisioningReview.objects.get_or_create(
        application=app,
        defaults={
            "domain": domain,
            "metadata_document": dict(metadata_document) if metadata_document is not None else None,
            "run_log": [_log_entry("registered", f"{app.name} registered for provisioning from {app.client_id}")],
        },
    )
    return review


def append_run_log(application_id: str, step: str, message: str, *, level: str = "info", **details: Any) -> None:
    with transaction.atomic():
        review = CIMDProvisioningReview.objects.select_for_update().filter(application_id=application_id).first()
        if review is None:
            return
        review.run_log = [*review.run_log, _log_entry(step, message, level=level, **details)][-MAX_RUN_LOG_ENTRIES:]
        review.save(update_fields=["run_log"])


def review_workflow_id(application_id: str) -> str:
    return f"cimd-provisioning-review-{application_id}"


def start_review(application_id: str) -> None:
    """Queue the start of the review workflow, at most once per dedup window.

    The registration request only enqueues, so a slow or unreachable Temporal never holds it.
    The task retries on its own, and a partner's next registration call queues it again once
    the window passes (see ``ensure_review_running``).
    """
    if cache.add(f"cimd-provisioning-review-dispatch:{application_id}", True, timeout=REVIEW_DISPATCH_DEDUP_SECONDS):
        start_review_workflow_task.delay(application_id)


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=REVIEW_DISPATCH_MAX_RETRIES,
)
def start_review_workflow_task(application_id: str) -> None:
    """Start the review workflow, or join the run already in flight for this app."""
    # Imports deferred to keep the Temporal stack off the web import path.
    from temporalio.common import WorkflowIDConflictPolicy

    from posthog.temporal.cimd_provisioning_review.types import CIMDProvisioningReviewInputs
    from posthog.temporal.cimd_provisioning_review.workflow import CIMDProvisioningReviewWorkflow
    from posthog.temporal.common.client import async_connect

    async def _connect_and_start() -> None:
        client = await asyncio.wait_for(async_connect(), timeout=REVIEW_DISPATCH_TIMEOUT_SECONDS)
        await asyncio.wait_for(
            client.start_workflow(
                CIMDProvisioningReviewWorkflow.run,
                CIMDProvisioningReviewInputs(application_id=application_id),
                id=review_workflow_id(application_id),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            ),
            timeout=REVIEW_DISPATCH_TIMEOUT_SECONDS,
        )

    asyncio.run(_connect_and_start())


def pending_review(app: OAuthApplication) -> CIMDProvisioningReview | None:
    return CIMDProvisioningReview.objects.filter(application=app, status=ProvisioningReviewStatus.PENDING).first()


def ensure_review_running(app: OAuthApplication) -> CIMDProvisioningReview | None:
    """Return the app's pending review after making sure a workflow is working on it.

    Starting again is safe: a run already in flight absorbs the start, and a run that ended
    without settling the review (a worker lost mid-run, say) gets a fresh one.
    """
    review = pending_review(app)
    if review is not None:
        start_review(str(app.pk))
    return review


# PostHog serves documents that its own customers control under paths on these domains, such as
# webhook responses, so one tenant's accepted client must not vouch for another tenant's.
SHARED_POSTHOG_DOMAINS = frozenset({"posthog.com"})


def _client_id_host(client_id: str) -> str | None:
    try:
        return urlparse(client_id).hostname
    except ValueError:
        return None


def host_already_accepted(client_id: str, *, domain: str, excluding_application_id: str) -> bool:
    """Whether another client whose metadata document is on the same host already passed a review
    and is still an active partner. The match is on the host, not the registrable domain, because a
    hosting platform missing from the public suffix list gives every tenant a subdomain of one
    registrable domain. An IP host has no registrable domain, so an empty domain never matches."""
    host = _client_id_host(client_id)
    if not host or not domain or domain in SHARED_POSTHOG_DOMAINS:
        return False
    accepted_client_ids = (
        CIMDProvisioningReview.objects.filter(
            domain=domain,
            status=ProvisioningReviewStatus.ACCEPTED,
            application__is_provisioning_partner=True,
            application___provisioning_config__active=True,
        )
        # Blocking a partner after it was accepted withdraws its vouching for the host too.
        .exclude(application___provisioning_config__disabled=True)
        .exclude(application_id=excluding_application_id)
        .values_list("application__client_id", flat=True)
    )
    return any(_client_id_host(accepted) == host for accepted in accepted_client_ids)


def _write_verdict(
    review: CIMDProvisioningReview,
    *,
    status: ProvisioningReviewStatus,
    stage: ProvisioningReviewStage,
    reason: str,
) -> str:
    """Save the verdict on a review locked by the caller, and return the status it replaced."""
    previous = review.status
    if previous in (ProvisioningReviewStatus.ACCEPTED, ProvisioningReviewStatus.REJECTED):
        message = f"Changed from {ProvisioningReviewStatus(previous).label} to {status.label}: {reason}"
    else:
        message = f"{status.label}: {reason}"
    review.status = status
    review.decided_stage = stage
    review.reason = reason
    review.decided_at = timezone.now()
    review.run_log = [
        *review.run_log,
        _log_entry("settled", message, level="info" if status == ProvisioningReviewStatus.ACCEPTED else "warning"),
    ][-MAX_RUN_LOG_ENTRIES:]
    review.save(update_fields=["status", "decided_stage", "reason", "decided_at", "run_log", "partner_message"])
    return previous


def _capture_settled(review: CIMDProvisioningReview, *, previous_status: str) -> None:
    app = review.application
    assert review.decided_at is not None
    posthoganalytics.capture(
        distinct_id=app.client_id,
        event="cimd_provisioning_review_settled",
        properties={
            "cimd_url": app.client_id,
            "client_name": app.name,
            "app_id": str(app.pk),
            "domain": review.domain,
            "status": review.status,
            "previous_status": previous_status,
            "stage": review.decided_stage,
            "reason": review.reason,
            "review_id": str(review.pk),
            "review_url": application_console_url(app.pk),
            "region": get_instance_region(),
            "review_seconds": (review.decided_at - review.created_at).total_seconds(),
        },
    )
    review_id, status = str(review.pk), review.status
    transaction.on_commit(lambda: send_partner_review_email.delay(review_id, status))
    queue_review_slack_thread(review, previous_status=previous_status)


# Review outcomes the partner's organization admins hear about. A pending review stays quiet.
REVIEW_EMAIL_TEMPLATES = {
    ProvisioningReviewStatus.ACCEPTED: "oauth_app_provisioning_accepted",
    ProvisioningReviewStatus.REJECTED: "oauth_app_provisioning_rejected",
    ProvisioningReviewStatus.NEEDS_HUMAN: "oauth_app_provisioning_in_review",
}
REVIEW_EMAIL_SUBJECTS = {
    ProvisioningReviewStatus.ACCEPTED: "{app_name} is approved for provisioning",
    ProvisioningReviewStatus.REJECTED: "{app_name} wasn't approved for provisioning",
    ProvisioningReviewStatus.NEEDS_HUMAN: "{app_name} is waiting for a manual review",
}


def partner_review_url() -> str:
    """The settings page where the app's organization admins read its review."""
    return f"{settings.SITE_URL}/settings/organization-oauth-apps"


@shared_task(**EMAIL_TASK_KWARGS)
@skip_team_scope_audit
def send_partner_review_email(review_id: str, status: str) -> None:
    """Tell the admins and owners of the organization that owns the app where its review landed.

    An app with no organization has nobody to tell, which is one reason linking matters.
    """
    if not is_email_available(with_absolute_urls=True):
        return
    review = CIMDProvisioningReview.objects.select_related("application__organization").filter(pk=review_id).first()
    # A later decision replaced this one and sends its own email.
    if review is None or review.status != status or review.decided_at is None:
        return
    template_name = REVIEW_EMAIL_TEMPLATES.get(ProvisioningReviewStatus(status))
    app = review.application
    organization = app.organization
    if template_name is None or organization is None:
        return

    memberships = (
        OrganizationMembership.objects.select_related("user")
        .with_effective_level()
        .filter(
            organization=organization,
            resolved_level__gte=OrganizationMembership.Level.ADMIN,
            user__is_active=True,
        )
    )
    recipients = [membership.user for membership in memberships if membership.user.email]
    if not recipients:
        return

    # The app names itself in its metadata document, so the name is untrusted.
    app_name = sanitize_display_name(
        app.name,
        fallback="Your OAuth application",
        context={"task": "send_partner_review_email", "field": "app_name", "review_id": review_id},
    )
    message = EmailMessage(
        campaign_key=f"oauth_app_review_{review.pk}_{status}_{review.decided_at.timestamp()}",
        subject=REVIEW_EMAIL_SUBJECTS[ProvisioningReviewStatus(status)].format(app_name=app_name),
        template_name=template_name,
        use_http=True,
        template_context={
            "app_name": app_name,
            "client_id": app.client_id,
            "partner_message": review.partner_message,
            "review_url": partner_review_url(),
            **get_email_team_and_org_context(organization=organization),
        },
    )
    for user in recipients:
        message.add_user_recipient(user)
    message.send()


def settle_review(
    application_id: str,
    *,
    status: ProvisioningReviewStatus,
    stage: ProvisioningReviewStage,
    reason: str,
) -> bool:
    """Write the pipeline's verdict and apply it to the app. Returns False when the review is no
    longer pending, which leaves a decision staff made in place. Staff decide with ``decide_partner``."""
    if status == ProvisioningReviewStatus.PENDING:
        raise ValueError("A review cannot be settled as pending")

    with transaction.atomic():
        review = (
            CIMDProvisioningReview.objects.select_for_update()
            .select_related("application")
            .get(application_id=application_id)
        )
        if review.status != ProvisioningReviewStatus.PENDING:
            return False
        previous = _write_verdict(review, status=status, stage=stage, reason=reason)

        app = review.application
        if status == ProvisioningReviewStatus.ACCEPTED and not app.provisioning.disabled:
            app.update_provisioning(active=True)
        elif status == ProvisioningReviewStatus.REJECTED:
            _block(app)

    _capture_settled(review, previous_status=previous)
    return True


def _block(app: OAuthApplication) -> None:
    app.update_provisioning(active=False, disabled=True)
    # In the same transaction as the verdict: a revocation that failed after a committed
    # rejection would leave live tokens that no retry revisits, since the review is settled.
    revoke_application_sessions(app)


def decide_partner(app: OAuthApplication, *, accept: bool, reason: str, partner_message: str = "") -> None:
    """Staff turn a provisioning partner on, or block it. Either decision can be reversed later,
    and the app's review, when it has one, records each one in its run log. ``partner_message``
    replaces what the partner's organization admins see on the review."""
    status = ProvisioningReviewStatus.ACCEPTED if accept else ProvisioningReviewStatus.REJECTED
    previous: str | None = None
    with transaction.atomic():
        review = (
            CIMDProvisioningReview.objects.select_for_update()
            .select_related("application")
            .filter(application=app)
            .first()
        )
        if review is not None:
            review.partner_message = partner_message
            if review.status == status:
                review.save(update_fields=["partner_message"])
            else:
                previous = _write_verdict(review, status=status, stage=ProvisioningReviewStage.STAFF, reason=reason)
        if accept:
            app.update_provisioning(active=True, disabled=False)
        else:
            _block(app)

    if previous is not None:
        assert review is not None
        _capture_settled(review, previous_status=previous)


def partner_provisioning_status(
    app: OAuthApplication, review: CIMDProvisioningReview | None
) -> PartnerProvisioningStatus:
    """Whether the app can provision right now, following `provisioning_allowed`, which every partner
    gate reads. An allowed partner is on even when `disabled` is also set."""
    config = app.provisioning
    if app.is_provisioning_partner and app.provisioning_allowed:
        return PartnerProvisioningStatus.ON
    if config.disabled:
        return PartnerProvisioningStatus.BLOCKED
    if not app.is_provisioning_partner:
        return PartnerProvisioningStatus.NOT_A_PARTNER
    if review is not None and review.status == ProvisioningReviewStatus.PENDING:
        return PartnerProvisioningStatus.IN_REVIEW
    if review is not None and review.status == ProvisioningReviewStatus.NEEDS_HUMAN:
        return PartnerProvisioningStatus.WAITING_FOR_STAFF
    return PartnerProvisioningStatus.OFF
