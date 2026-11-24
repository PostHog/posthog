"""The staff Slack thread for each provisioning partner review, in PostHog's own Slack workspace.

The first time a review settles, PostHog posts it to `PROVISIONING_REVIEW_SLACK_CHANNEL`. Every later
decision edits that message to show the current state and replies under it, so the whole history of a
partner stays in one thread. The message carries a Block button for staff. Accepting stays in PostHog
Admin, because granting account creation should keep the admin step-up that a Slack click skips.

The bot is its own Slack app. Its clicks arrive through `posthog/ingress` at
`webhooks/provisioning-reviews/slack/interactivity`, which forwards each one to the region named in its
block id and calls `handle_interaction`.
"""

import json
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

import structlog
from celery import Task, shared_task
from redis.exceptions import LockError, RedisError
from slack_sdk.errors import SlackApiError

from posthog.egress.slack.client import SlackWebClient
from posthog.ingress.contracts import DeliveryOwnership
from posthog.models.oauth_provisioning_review import CIMDProvisioningReview, ProvisioningReviewStatus
from posthog.models.user import User
from posthog.redis import get_client
from posthog.slack.identity import resolve_slack_user
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

BLOCK_ACTION_ID = "cimd_review_block"
# A URL button still sends Slack a click, which the consumer acknowledges and ignores.
OPEN_ACTION_ID = "cimd_review_open"
# Slack enforces this on the form, because the endpoint's answer cannot carry a validation error.
BLOCK_REASON_MIN_LENGTH = 3
BLOCK_MODAL_CALLBACK_ID = "cimd_review_block_modal"
BLOCK_MODAL_REASON_BLOCK = "cimd_review_block_reason"
BLOCK_MODAL_REASON_INPUT = "reason"
# The block id carries the review's region, so the interactivity endpoint can route a click to the
# region that holds the review before anything reads the database.
BLOCK_ID_PREFIX = "cimd_review"
WORKSPACE_CACHE_KEY = "cimd_review_slack_workspace_id"
THREAD_LOCK_PREFIX = "cimd_review_slack_thread"
# Above the three Slack calls a sync makes at their 30-second client timeout.
THREAD_LOCK_SECONDS = 120
THREAD_RETRY_SECONDS = 5
# Contention backs off for about five minutes in total, past the lock's lease.
THREAD_MAX_RETRIES = 6
THREAD_POSTED_SECONDS = 60 * 60 * 24
WORKSPACE_CACHE_SECONDS = 60 * 60

STATUS_HEADINGS = {
    ProvisioningReviewStatus.ACCEPTED: ":white_check_mark: Provisioning partner accepted",
    ProvisioningReviewStatus.DECLINED: ":x: Provisioning partner declined",
    ProvisioningReviewStatus.CHANGES_REQUESTED: ":leftwards_arrow_with_hook: Provisioning partner sent back for changes",
    ProvisioningReviewStatus.REJECTED: ":no_entry: Provisioning partner blocked",
    ProvisioningReviewStatus.NEEDS_HUMAN: ":eyes: Provisioning partner needs a staff review",
    ProvisioningReviewStatus.PENDING: ":hourglass: Provisioning partner in review",
}


def slack_thread_configured() -> bool:
    return bool(settings.PROVISIONING_REVIEW_SLACK_BOT_TOKEN and settings.PROVISIONING_REVIEW_SLACK_CHANNEL)


def _client() -> SlackWebClient:
    return SlackWebClient(
        token=settings.PROVISIONING_REVIEW_SLACK_BOT_TOKEN, source="cimd_provisioning_review", app_id="posthog"
    )


def _region() -> str:
    return get_instance_region() or ""


def _escape(text: str) -> str:
    # The partner names its own app, so its name must not become a mention or a link in Slack.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def review_region(payload: Mapping[str, Any]) -> str | None:
    """The region of the review a Slack payload is about, or None when the payload isn't about a review."""
    for action in payload.get("actions") or ():
        parts = str(action.get("block_id", "")).split(":")
        if len(parts) == 3 and parts[0] == BLOCK_ID_PREFIX:
            return parts[1]
    view = payload.get("view") or {}
    if view.get("callback_id") == BLOCK_MODAL_CALLBACK_ID:
        try:
            return str(json.loads(view.get("private_metadata") or "{}").get("region", ""))
        except (json.JSONDecodeError, AttributeError):
            return ""
    return None


def render_review_message(review: CIMDProvisioningReview) -> tuple[str, list[dict[str, Any]]]:
    from posthog.api.oauth.provisioning_review import application_console_url  # noqa: PLC0415 - import cycle

    app = review.application
    status = ProvisioningReviewStatus(review.status)
    name = _escape(app.name or app.client_id)
    heading = f"{STATUS_HEADINGS[status]}: {name}"
    blocked = app.provisioning.disabled and not app.provisioning.active
    details = [f"*Domain:* `{_escape(review.domain)}`", f"*Region:* {_region() or 'self-hosted'}"]
    if review.decided_stage:
        details.append(f"*Decided at:* {review.decided_stage}")
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{heading}*"}},
        {"type": "section", "fields": [{"type": "mrkdwn", "text": detail} for detail in details]},
    ]
    if review.reason:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _escape(review.reason)[:2900]}})
    blocks.append({"type": "context", "elements": [{"type": "plain_text", "text": app.client_id[:2900]}]})
    actions: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Open in PostHog Admin"},
            "url": application_console_url(app.pk),
            "action_id": OPEN_ACTION_ID,
        }
    ]
    if not blocked:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Block"},
                "style": "danger",
                "action_id": BLOCK_ACTION_ID,
                "value": str(review.pk),
            }
        )
    blocks.append({"type": "actions", "block_id": f"{BLOCK_ID_PREFIX}:{_region()}:{review.pk}", "elements": actions})
    return heading, blocks


def _retry_countdown(error: Exception, retries: int) -> int:
    if isinstance(error, SlackApiError) and error.response.status_code == 429:
        # Slack names how long to wait, and a backoff shorter than that spends every retry inside the limit.
        return int(error.response.headers.get("Retry-After", THREAD_RETRY_SECONDS))
    return THREAD_RETRY_SECONDS * 2**retries


@shared_task(bind=True, ignore_result=True, max_retries=THREAD_MAX_RETRIES)
def sync_review_slack_thread(
    self: Task,
    review_id: str,
    status: str,
    previous_status: str | None = None,
    reason: str = "",
    always_reply: bool = False,
) -> None:
    """Post the review's thread the first time it settles, then keep the first message current and reply
    with each decision. The reply describes the decision this task was queued for, which a later one may
    already have replaced."""
    if not slack_thread_configured():
        return
    # One task per review talks to Slack at a time, so two first decisions can't post two threads. The lock
    # is owned by a token, so a task whose work outlasted the lease can't release the next task's lock, and the
    # backoff outlasts the lease, so a lock a dead worker left behind can't use up every retry.
    lock = get_client().lock(f"{THREAD_LOCK_PREFIX}:{review_id}", timeout=THREAD_LOCK_SECONDS)
    try:
        acquired = lock.acquire(blocking=False)
    except RedisError as error:
        raise self.retry(exc=error, countdown=_retry_countdown(error, self.request.retries))
    if not acquired:
        raise self.retry(countdown=THREAD_RETRY_SECONDS * 2**self.request.retries)
    try:
        _sync_review_slack_thread(
            review_id, status=status, previous_status=previous_status, reason=reason, always_reply=always_reply
        )
    except Exception as error:
        raise self.retry(exc=error, countdown=_retry_countdown(error, self.request.retries))
    finally:
        with suppress(LockError):
            lock.release()


def _sync_review_slack_thread(
    review_id: str, *, status: str, previous_status: str | None, reason: str, always_reply: bool = False
) -> None:
    review = CIMDProvisioningReview.objects.select_related("application").filter(pk=review_id).first()
    if review is None or status == ProvisioningReviewStatus.PENDING:
        return
    client = _client()
    text, blocks = render_review_message(review)

    if not review.slack_message_ts:
        # A post that Slack accepted but the database never recorded is reused rather than posted again.
        posted_key = f"{THREAD_LOCK_PREFIX}:posted:{review.pk}"
        posted = cache.get(posted_key)
        if posted is None:
            response = client.chat_postMessage(
                channel=settings.PROVISIONING_REVIEW_SLACK_CHANNEL, text=text, blocks=blocks, unfurl_links=False
            )
            posted = (response["channel"], response["ts"], status)
            cache.set(posted_key, posted, THREAD_POSTED_SECONDS)
        channel_id, message_ts, posted_status = posted
        CIMDProvisioningReview.objects.filter(pk=review.pk).update(
            slack_channel_id=channel_id, slack_message_ts=message_ts
        )
        # The post already shows the decision that made it. A later decision, or a partner note, still updates
        # it and replies, because the post shows neither the note nor the earlier status.
        if posted_status == status and previous_status != status and not always_reply:
            return
        review.slack_channel_id, review.slack_message_ts = channel_id, message_ts

    client.chat_update(channel=review.slack_channel_id, ts=review.slack_message_ts, text=text, blocks=blocks)
    change = ProvisioningReviewStatus(status).label
    if previous_status and previous_status != status:
        reply = f"{ProvisioningReviewStatus(previous_status).label} → {change}"
    else:
        reply = change
    if reason:
        reply = f"{reply}: {_escape(reason)}"
    client.chat_postMessage(channel=review.slack_channel_id, thread_ts=review.slack_message_ts, text=reply[:3000])


def queue_review_slack_thread(
    review: CIMDProvisioningReview, *, previous_status: str | None, reply: str | None = None
) -> None:
    # Queued without checking the bot settings: reviews settle on a Temporal worker that does not carry them,
    # and the task checks them on the Celery worker that talks to Slack.
    args = (str(review.pk), str(review.status), previous_status, review.reason if reply is None else reply)
    always_reply = reply is not None
    transaction.on_commit(lambda: sync_review_slack_thread.delay(*args, always_reply=always_reply))


def _workspace_id(client: SlackWebClient) -> str | None:
    cached = cache.get(WORKSPACE_CACHE_KEY)
    if cached:
        return cached
    team_id = client.auth_test().get("team_id")
    if team_id:
        cache.set(WORKSPACE_CACHE_KEY, team_id, WORKSPACE_CACHE_SECONDS)
    return team_id


def staff_user_for_slack_user(payload: Mapping[str, Any]) -> User | None:
    """The active PostHog staff user behind a Slack click, or None.

    Only a member of PostHog's own workspace counts, so a Slack Connect guest in the channel can't act
    with an email that matches a staff account.
    """
    if not slack_thread_configured():
        return None
    slack_user_id = (payload.get("user") or {}).get("id") or ""
    client = _client()
    workspace_id = _workspace_id(client)
    if not workspace_id or (payload.get("team") or {}).get("id") != workspace_id:
        return None
    slack_user = resolve_slack_user(client, slack_user_id, workspace=workspace_id)
    email = slack_user.get("email")
    if not email or slack_user.get("team_id") != workspace_id:
        return None
    return User.objects.filter(email__iexact=email, is_staff=True, is_active=True).first()


def _review_for_action(payload: Mapping[str, Any]) -> CIMDProvisioningReview | None:
    for action in payload.get("actions") or ():
        if action.get("action_id") == BLOCK_ACTION_ID:
            return CIMDProvisioningReview.objects.select_related("application").filter(pk=action.get("value")).first()
    return None


def handle_block_click(payload: Mapping[str, Any]) -> None:
    """Open the reason form for a staff member who clicked Block. The block itself happens on submit."""
    review = _review_for_action(payload)
    trigger_id = payload.get("trigger_id")
    if review is None or not trigger_id:
        return
    client = _client()
    if staff_user_for_slack_user(payload) is None:
        client.chat_postEphemeral(
            channel=(payload.get("channel") or {}).get("id", ""),
            user=(payload.get("user") or {}).get("id", ""),
            text="Only PostHog staff can block a provisioning partner.",
        )
        return
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": BLOCK_MODAL_CALLBACK_ID,
            "private_metadata": json.dumps({"review_id": str(review.pk), "region": _region()}),
            "title": {"type": "plain_text", "text": "Block partner"},
            "submit": {"type": "plain_text", "text": "Block"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"Block *{_escape(review.application.name)}*? It stops provisioning and every "
                            "connection it has is signed out. You can accept it again in PostHog Admin."
                        ),
                    },
                },
                {
                    "type": "input",
                    "block_id": BLOCK_MODAL_REASON_BLOCK,
                    "label": {"type": "plain_text", "text": "Reason"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": BLOCK_MODAL_REASON_INPUT,
                        "multiline": True,
                        "min_length": BLOCK_REASON_MIN_LENGTH,
                    },
                },
            ],
        },
    )


def interaction_ownership(payload: Mapping[str, Any]) -> DeliveryOwnership:
    """Which region holds the review a click is about, read from the block id or the form."""
    region = review_region(payload)
    if region is None:
        return DeliveryOwnership.UNDECIDED
    return DeliveryOwnership.LOCAL if region == _region() else DeliveryOwnership.ELSEWHERE


def handle_interaction(payload: Mapping[str, Any]) -> None:
    """Run a staff bot click. Opening the form stays in the request, because Slack's trigger id expires
    after three seconds; the block itself runs in a task."""
    if payload.get("type") == "block_actions":
        if any(action.get("action_id") == BLOCK_ACTION_ID for action in payload.get("actions") or ()):
            handle_block_click(payload)
        return
    view = payload.get("view") or {}
    if payload.get("type") != "view_submission" or view.get("callback_id") != BLOCK_MODAL_CALLBACK_ID:
        return
    try:
        review_id = str(json.loads(view.get("private_metadata") or "{}").get("review_id") or "")
    except (json.JSONDecodeError, AttributeError):
        return
    reason = (
        ((view.get("state") or {}).get("values") or {})
        .get(BLOCK_MODAL_REASON_BLOCK, {})
        .get(BLOCK_MODAL_REASON_INPUT, {})
        .get("value")
        or ""
    ).strip()
    if review_id and reason:
        block_partner_from_slack.delay(
            review_id,
            slack_team_id=(payload.get("team") or {}).get("id") or "",
            slack_user_id=(payload.get("user") or {}).get("id") or "",
            reason=reason,
        )


@shared_task(ignore_result=True)
def block_partner_from_slack(review_id: str, *, slack_team_id: str, slack_user_id: str, reason: str) -> None:
    """Block the partner from the staff bot's form. Staff are checked again here, because anyone with the
    form open can submit it."""
    from posthog.api.oauth.provisioning_review import decide_partner  # noqa: PLC0415 - import cycle

    staff = staff_user_for_slack_user({"team": {"id": slack_team_id}, "user": {"id": slack_user_id}})
    if staff is None:
        logger.warning("cimd_review_slack_block_refused", review_id=review_id, slack_user_id=slack_user_id)
        return
    review = CIMDProvisioningReview.objects.select_related("application").filter(pk=review_id).first()
    if review is None:
        return
    decide_partner(
        review.application,
        decision=ProvisioningReviewStatus.REJECTED,
        reason=f"Staff ({staff.email}, from Slack): {reason}",
        actor=staff.email,
    )
    logger.info("cimd_review_blocked_from_slack", review_id=review_id, staff_user_id=staff.pk)
