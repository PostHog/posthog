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

from posthog.cloud_utils import is_cloud
from posthog.llm.system_one_client import system_one_configured
from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

REVIEW_DISPATCH_TIMEOUT_SECONDS = 5
REVIEW_DISPATCH_MAX_RETRIES = 8
# A partner polls the registration endpoint while it waits, and every poll asks for the review to
# be running. Inside this window that request costs no Temporal round trip.
REVIEW_DISPATCH_DEDUP_SECONDS = 60
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
    review.save(update_fields=["status", "decided_stage", "reason", "decided_at", "run_log"])
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


def decide_partner(app: OAuthApplication, *, accept: bool, reason: str) -> None:
    """Staff turn a provisioning partner on, or block it. Either decision can be reversed later,
    and the app's review, when it has one, records each one in its run log."""
    status = ProvisioningReviewStatus.ACCEPTED if accept else ProvisioningReviewStatus.REJECTED
    previous: str | None = None
    with transaction.atomic():
        review = (
            CIMDProvisioningReview.objects.select_for_update()
            .select_related("application")
            .filter(application=app)
            .first()
        )
        if review is not None and review.status != status:
            previous = _write_verdict(review, status=status, stage=ProvisioningReviewStage.STAFF, reason=reason)
        if accept:
            app.update_provisioning(active=True, disabled=False)
        else:
            _block(app)

    if review is not None and previous is not None:
        _capture_settled(review, previous_status=previous)
