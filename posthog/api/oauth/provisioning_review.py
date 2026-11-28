"""Opens, starts and settles the review a self-registered CIMD provisioning partner goes through.

A partner under review has its provisioning config written but left inactive, so every partner
endpoint refuses it the way it refuses a deactivated partner. Accepting turns it on. Declining, or
asking for changes, keeps it off, and the partner's organization admins can answer with a note
that sends the review back to staff. Declining and blocking revoke the app's sessions. Blocking,
which only staff do, also sets the ``disabled`` kill switch, which neither re-registering nor a note
can clear. Staff
can reverse any verdict later, and the review keeps each change in its run log. The pipeline that
reaches the verdict is ``posthog/temporal/cimd_provisioning_review/``.
"""

import json
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
from posthog.dataclasses import frozen
from posthog.email import EMAIL_TASK_KWARGS, EmailMessage, get_email_team_and_org_context, is_email_available
from posthog.helpers.email_utils import sanitize_display_name
from posthog.llm.system_one_client import system_one_configured
from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    OrganizationLinkState,
    PartnerAuthentication,
    PartnerProvisioningStatus,
    PartnerReviewEventKind,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.scopes.ceilings import DEFAULT_CEILING_SENTINEL, effective_ceiling
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
PARTNER_NOTE_MAX_LENGTH = 4000
# Notes the run log keeps per review, so partner text can't push the pipeline's evidence and the staff
# decisions out of the capped log.
MAX_PARTNER_NOTES_IN_RUN_LOG = 20
# Each note posts to the staff Slack thread. Answering a decision is never held back, because a decision
# has to happen between two answers.
PARTNER_NOTE_COOLDOWN_SECONDS = 10 * 60
PARTNER_NOTE_STEP = "partner_note"
SETTLED_STEP = "settled"
STAFF_MESSAGE_STEP = "partner_message"
REGISTERED_STEP = "registered"
# A partner already waiting for staff can add to what it told them.
PARTNER_NOTE_STATUSES = frozenset(
    {
        ProvisioningReviewStatus.DECLINED,
        ProvisioningReviewStatus.CHANGES_REQUESTED,
        ProvisioningReviewStatus.NEEDS_HUMAN,
    }
)


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
            "run_log": [_log_entry(REGISTERED_STEP, f"{app.name} registered for provisioning from {app.client_id}")],
        },
    )
    return review


def append_run_log(application_id: str, step: str, message: str, *, level: str = "info", **details: Any) -> None:
    with transaction.atomic():
        review = CIMDProvisioningReview.objects.select_for_update().filter(application_id=application_id).first()
        if review is None:
            return
        review.run_log = _append_to_run_log(review.run_log, _log_entry(step, message, level=level, **details))
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
    actor: str = "",
) -> str:
    """Save the verdict on a review locked by the caller, and return the status it replaced. The log entry keeps
    the status and the message the partner was shown, so the partner's timeline can be rebuilt from it."""
    previous = review.status
    message = _settled_message(previous, status, reason)
    review.status = status
    review.decided_stage = stage
    review.reason = reason
    review.decided_at = timezone.now()
    review.run_log = _append_to_run_log(
        review.run_log,
        _log_entry(
            SETTLED_STEP,
            message,
            level="info" if status == ProvisioningReviewStatus.ACCEPTED else "warning",
            status=str(status),
            stage=str(stage),
            actor=actor,
            partner_message=review.partner_message,
            organization_id=_organization_id(review.application),
        ),
    )
    review.save(update_fields=["status", "decided_stage", "reason", "decided_at", "run_log", "partner_message"])
    return previous


VERDICTS = frozenset(
    {
        ProvisioningReviewStatus.ACCEPTED,
        ProvisioningReviewStatus.DECLINED,
        ProvisioningReviewStatus.CHANGES_REQUESTED,
        ProvisioningReviewStatus.REJECTED,
    }
)


def _settled_message(previous: str, status: ProvisioningReviewStatus, reason: str) -> str:
    if previous in VERDICTS:
        return f"Changed from {ProvisioningReviewStatus(previous).label} to {status.label}: {reason}"
    return f"{status.label}: {reason}"


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


# Review outcomes the partner's organization admins hear about. A pending review stays quiet, and so does
# one that went back to staff because those admins asked for it.
REVIEW_EMAIL_TEMPLATES = {
    ProvisioningReviewStatus.ACCEPTED: "oauth_app_provisioning_accepted",
    ProvisioningReviewStatus.DECLINED: "oauth_app_provisioning_declined",
    ProvisioningReviewStatus.CHANGES_REQUESTED: "oauth_app_provisioning_changes_requested",
    ProvisioningReviewStatus.REJECTED: "oauth_app_provisioning_rejected",
    ProvisioningReviewStatus.NEEDS_HUMAN: "oauth_app_provisioning_in_review",
}
REVIEW_EMAIL_SUBJECTS = {
    ProvisioningReviewStatus.ACCEPTED: "{app_name} is approved for provisioning",
    ProvisioningReviewStatus.DECLINED: "{app_name} wasn't approved for provisioning",
    ProvisioningReviewStatus.CHANGES_REQUESTED: "PostHog needs more information about {app_name}",
    ProvisioningReviewStatus.REJECTED: "{app_name} is blocked from provisioning",
    ProvisioningReviewStatus.NEEDS_HUMAN: "{app_name} is waiting for a manual review",
}


def partner_review_url(app: OAuthApplication) -> str:
    """The settings page where the app's organization admins read its review and answer it."""
    return f"{settings.SITE_URL}/settings/organization-oauth-apps/{app.pk}"


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
            "partner_message": partner_message_for_current_organization(review),
            "review_url": partner_review_url(app),
            **get_email_team_and_org_context(organization=organization),
        },
    )
    for user in recipients:
        message.add_user_recipient(user)
    message.send()


PIPELINE_VERDICTS = frozenset(
    {ProvisioningReviewStatus.ACCEPTED, ProvisioningReviewStatus.DECLINED, ProvisioningReviewStatus.NEEDS_HUMAN}
)


def settle_review(
    application_id: str,
    *,
    status: ProvisioningReviewStatus,
    stage: ProvisioningReviewStage,
    reason: str,
) -> bool:
    """Write the pipeline's verdict and apply it to the app. Returns False when the review is no
    longer pending, which leaves a decision staff made in place. Staff decide with ``decide_partner``,
    and only staff block or ask for changes."""
    if status not in PIPELINE_VERDICTS:
        raise ValueError(f"The pipeline cannot settle a review as {status}")

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
        elif status == ProvisioningReviewStatus.DECLINED:
            _decline(app)

    _capture_settled(review, previous_status=previous)
    return True


def _block(app: OAuthApplication) -> None:
    app.update_provisioning(active=False, disabled=True)
    # In the same transaction as the verdict: a revocation that failed after a committed
    # rejection would leave live tokens that no retry revisits, since the review is settled.
    revoke_application_sessions(app)


def _decline(app: OAuthApplication) -> None:
    """Like a block, a decline signs out every connection, because the pipeline declines the apps it judges
    malicious. It leaves the kill switch off, so the partner's organization can ask for another review."""
    app.update_provisioning(active=False, disabled=False)
    revoke_application_sessions(app)


# Without a review the partner has nowhere to read a decision or answer it, so staff only turn it on or block it.
DECISIONS_WITHOUT_REVIEW = frozenset({ProvisioningReviewStatus.ACCEPTED, ProvisioningReviewStatus.REJECTED})


def decide_partner(
    app: OAuthApplication,
    *,
    decision: ProvisioningReviewStatus,
    reason: str,
    partner_message: str = "",
    actor: str = "",
) -> None:
    """Staff accept a provisioning partner, decline it, ask it for changes, or block it. Any decision
    can be reversed later, and the app's review, when it has one, records each one in its run log.
    ``partner_message`` replaces what the partner's organization admins see on the review, and asking
    for changes needs one, because it is the only place the partner learns what to change."""
    if decision not in VERDICTS:
        raise ValueError(f"Staff cannot decide {decision}")
    if decision == ProvisioningReviewStatus.CHANGES_REQUESTED and not partner_message.strip():
        raise ValueError("Asking a partner for changes needs a message that says what to change")
    previous: str | None = None
    with transaction.atomic():
        review = (
            CIMDProvisioningReview.objects.select_for_update()
            .select_related("application")
            .filter(application=app)
            .first()
        )
        if review is None and decision not in DECISIONS_WITHOUT_REVIEW:
            raise ValueError(f"{app.name} has no review, so it can only be accepted or blocked")
        # Read on the locked row, so a block saved since the caller loaded the app is seen.
        if decision == ProvisioningReviewStatus.CHANGES_REQUESTED and review is not None:
            if review.application.provisioning.disabled:
                raise PartnerDecisionRefused(
                    f"{app.name} is blocked. Accept or decline it to lift the block before asking for changes."
                )
        if review is not None:
            message_changed = review.partner_message != partner_message
            review.partner_message = partner_message
            if review.status != decision:
                previous = _write_verdict(
                    review, status=decision, stage=ProvisioningReviewStage.STAFF, reason=reason, actor=actor
                )
            elif message_changed:
                review.run_log = _append_to_run_log(
                    review.run_log,
                    _log_entry(
                        STAFF_MESSAGE_STEP,
                        f"Message to the partner changed: {partner_message or '(none)'}",
                        status=str(decision),
                        actor=actor,
                        partner_message=partner_message,
                        organization_id=_organization_id(review.application),
                    ),
                )
                review.save(update_fields=["partner_message", "run_log"])
        if decision == ProvisioningReviewStatus.ACCEPTED:
            app.update_provisioning(active=True, disabled=False)
        elif decision == ProvisioningReviewStatus.REJECTED:
            _block(app)
        elif decision == ProvisioningReviewStatus.DECLINED:
            _decline(app)
        else:
            app.update_provisioning(active=False, disabled=False)

    if previous is not None:
        assert review is not None
        _capture_settled(review, previous_status=previous)


class PartnerDecisionRefused(Exception):
    """Staff can't make this decision on the app as it is now. The message says why."""


class PartnerNoteRefused(Exception):
    """The partner's organization cannot send a note on this review right now. The message says why, for its admins."""


def send_partner_note(app: OAuthApplication, *, user: User, note: str) -> CIMDProvisioningReview:
    """An admin of the partner's organization tells staff about the app, which sends a declined review, or one
    that asked for changes, back to staff. A blocked partner cannot send one, because only staff lift a block.

    The note lands in the run log and the Slack thread, where staff read it. The partner never sees the review's
    internal reason, so the note answers ``partner_message``."""
    note = note.strip()
    if not note:
        raise PartnerNoteRefused("Write a note for PostHog staff.")
    with transaction.atomic():
        review = (
            CIMDProvisioningReview.objects.select_for_update()
            .select_related("application")
            .filter(application=app)
            .first()
        )
        if review is None:
            raise PartnerNoteRefused("This application has no provisioning review to answer.")
        # Read from the locked review's app, so a block staff saved since the request read the app is seen.
        if review.application.provisioning.disabled:
            raise PartnerNoteRefused(
                "PostHog blocked provisioning for this application, so it can't be reviewed again."
            )
        if review.status not in PARTNER_NOTE_STATUSES:
            raise PartnerNoteRefused(
                f"This review is {ProvisioningReviewStatus(review.status).label.lower()}, so it isn't waiting for a note."
            )
        previous = review.status
        status = ProvisioningReviewStatus.NEEDS_HUMAN
        if previous == status and not cache.add(
            f"cimd-provisioning-review-note:{review.pk}", True, timeout=PARTNER_NOTE_COOLDOWN_SECONDS
        ):
            raise PartnerNoteRefused(
                "You sent a note a few minutes ago, and PostHog staff will read it. Wait a few minutes to add another."
            )
        message = (
            f"{user.email} asked for another review: {note}"
            if previous != status
            else f"{user.email} added a note: {note}"
        )
        review.status = status
        review.decided_stage = None
        review.decided_at = None
        review.run_log = _append_to_run_log(
            review.run_log,
            _log_entry(
                PARTNER_NOTE_STEP,
                message,
                user_id=user.pk,
                previous_status=previous,
                author=user.email,
                note=note,
                organization_id=_organization_id(review.application),
            ),
        )
        review.save(update_fields=["status", "decided_stage", "decided_at", "run_log"])

    posthoganalytics.capture(
        distinct_id=str(user.distinct_id),
        event="cimd_provisioning_review_note_sent",
        properties={
            "app_id": str(app.pk),
            "review_id": str(review.pk),
            "previous_status": previous,
            "status": review.status,
            "region": get_instance_region(),
        },
        groups={"organization": str(app.organization_id)} if app.organization_id else None,
    )
    queue_review_slack_thread(review, previous_status=previous, reply=message)
    return review


def _organization_id(app: OAuthApplication) -> str | None:
    return str(app.organization_id) if app.organization_id else None


def _is_added_note(entry: Mapping[str, Any]) -> bool:
    """A note sent while the review already waited for staff. It changed no status, unlike a note that reopened a
    decision, so it is the one entry the log may drop to stay within its caps."""
    return (
        entry.get("step") == PARTNER_NOTE_STEP and entry.get("previous_status") == ProvisioningReviewStatus.NEEDS_HUMAN
    )


def _append_to_run_log(run_log: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Append to the log within its caps. Only added notes are dropped while there are any, oldest first, so
    partner text can't push out a decision, a reopening or the pipeline's evidence."""
    log = [*run_log, entry]
    added_notes = [index for index, logged in enumerate(log) if _is_added_note(logged)]
    dropped = set(added_notes[: max(0, len(added_notes) - MAX_PARTNER_NOTES_IN_RUN_LOG)])
    log = [logged for index, logged in enumerate(log) if index not in dropped]
    while len(log) > MAX_RUN_LOG_ENTRIES:
        oldest_note = next((index for index, logged in enumerate(log) if _is_added_note(logged)), 0)
        del log[oldest_note]
    return log


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
    if review is not None and review.status == ProvisioningReviewStatus.CHANGES_REQUESTED:
        return PartnerProvisioningStatus.CHANGES_REQUESTED
    if review is not None and review.status == ProvisioningReviewStatus.DECLINED:
        return PartnerProvisioningStatus.DECLINED
    return PartnerProvisioningStatus.OFF


@frozen
class PartnerReviewEvent:
    at: str
    kind: PartnerReviewEventKind
    status: ProvisioningReviewStatus | None = None
    message: str = ""
    author: str = ""


AUTOMATED_STAGES = frozenset(
    {
        ProvisioningReviewStage.RESEARCH,
        ProvisioningReviewStage.HOST_ALREADY_ACCEPTED,
        ProvisioningReviewStage.PIPELINE_FAILED,
    }
)


def partner_timeline(review: CIMDProvisioningReview) -> list[PartnerReviewEvent]:
    """What happened on the review, oldest first, as the partner's organization admins may see it. The internal
    reason, the research and the staff member's name stay out, because they describe what the review checks."""
    events = [PartnerReviewEvent(at=review.created_at.isoformat(), kind=PartnerReviewEventKind.REGISTERED)]
    organization_id = _organization_id(review.application)
    for entry in review.run_log:
        event = _partner_event(entry, organization_id)
        if event is not None:
            events.append(event)
    return events


def partner_message_for_current_organization(review: CIMDProvisioningReview) -> str:
    """The staff message as the linked organization may read it: empty when it was written while the app was linked
    to another organization, or before messages recorded one."""
    organization_id = _organization_id(review.application)
    last_message = next(
        (entry for entry in reversed(review.run_log) if entry.get("step") in (SETTLED_STEP, STAFF_MESSAGE_STEP)),
        None,
    )
    if organization_id is None or last_message is None or last_message.get("organization_id") != organization_id:
        return ""
    return review.partner_message


def _partner_event(entry: Mapping[str, Any], organization_id: str | None) -> PartnerReviewEvent | None:
    step, at, status = entry.get("step"), str(entry.get("at", "")), entry.get("status")
    # Notes and staff messages were written to the organization linked then. A client_id can be relinked to
    # another organization, which must not read what was said to the last one.
    same_organization = organization_id is not None and entry.get("organization_id") == organization_id
    if step in (PARTNER_NOTE_STEP, STAFF_MESSAGE_STEP) and not same_organization:
        return None
    if step == PARTNER_NOTE_STEP and entry.get("note"):
        return PartnerReviewEvent(
            at=at,
            kind=PartnerReviewEventKind.PARTNER_NOTE,
            message=str(entry["note"]),
            author=str(entry.get("author", "")),
        )
    # Entries written before the log kept a status can't be shown without their internal reason.
    if status not in ProvisioningReviewStatus.values:
        return None
    if step == SETTLED_STEP and entry.get("stage") in AUTOMATED_STAGES:
        return PartnerReviewEvent(
            at=at, kind=PartnerReviewEventKind.AUTOMATED_REVIEW, status=ProvisioningReviewStatus(status)
        )
    if step == SETTLED_STEP:
        return PartnerReviewEvent(
            at=at,
            kind=PartnerReviewEventKind.STAFF_DECISION,
            status=ProvisioningReviewStatus(status),
            message=str(entry.get("partner_message", "")) if same_organization else "",
        )
    if step == STAFF_MESSAGE_STEP:
        return PartnerReviewEvent(
            at=at,
            kind=PartnerReviewEventKind.STAFF_MESSAGE,
            status=ProvisioningReviewStatus(status),
            message=str(entry.get("partner_message", "")),
        )
    return None


@frozen
class RegisteredPartnerDetails:
    """How PostHog treats the app now, from the app's own record, which every metadata refresh updates. The homepage,
    policy links and contacts are kept only in the document saved when the review opened. The document is the app's own
    public file, so its owners can see all of it."""

    client_name: str
    client_uri: str
    logo_uri: str
    tos_uri: str
    policy_uri: str
    contacts: list[str]
    redirect_uris: list[str]
    jwks_uri: str
    authentication: PartnerAuthentication
    scopes: list[str]
    uses_default_scopes: bool
    needs_signing_key: bool
    can_create_accounts: bool
    can_provision_resources: bool
    organization_link: OrganizationLinkState
    metadata_document: str


def _document_text(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    return value if isinstance(value, str) else ""


def _document_list(document: Mapping[str, Any], key: str) -> list[str]:
    value = document.get(key)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _uses_default_scopes(app_scopes: list[str]) -> bool:
    stripped = {scope.strip() for scope in app_scopes} - {""}
    return not stripped or DEFAULT_CEILING_SENTINEL in stripped


def registered_partner_details(
    app: OAuthApplication, review: CIMDProvisioningReview | None
) -> RegisteredPartnerDetails:
    document: Mapping[str, Any] = (review.metadata_document if review is not None else None) or {}
    if app.organization_id is not None:
        link = OrganizationLinkState.THIS_ORGANIZATION
    elif app.organization_link_issuer:
        link = OrganizationLinkState.OTHER_REGION
    else:
        link = OrganizationLinkState.NOT_LINKED
    return RegisteredPartnerDetails(
        client_name=app.name,
        client_uri=_document_text(document, "client_uri"),
        logo_uri=app.logo_uri or "",
        tos_uri=_document_text(document, "tos_uri"),
        policy_uri=_document_text(document, "policy_uri"),
        contacts=_document_list(document, "contacts"),
        redirect_uris=app.redirect_uris.split(),
        jwks_uri=app.jwks_uri or "",
        authentication=PartnerAuthentication(app.token_endpoint_auth_method.value),
        scopes=sorted(effective_ceiling(app.ceiling_scopes)),
        uses_default_scopes=_uses_default_scopes(app.ceiling_scopes),
        needs_signing_key=app.cannot_meet_provisioning_signature,
        can_create_accounts=app.provisioning.can_create_accounts,
        can_provision_resources=app.provisioning.can_provision_resources,
        organization_link=link,
        metadata_document=json.dumps(document, indent=2, sort_keys=True) if document else "",
    )
