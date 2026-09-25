"""Teams inbound events, outbound replies, and shared-channel polling."""

from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

import requests
import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit

from products.conversations.backend.models import TeamConversationsTeamsChannelSync, TeamConversationsTeamsConfig
from products.conversations.backend.models.constants import Channel, ChannelDetail, Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.support_teams import (
    get_bot_framework_token,
    get_bot_from_id,
    get_graph_token,
    invalidate_bot_framework_token,
    is_trusted_teams_service_url,
    store_teams_service_url,
)
from products.conversations.backend.teams import (
    GRAPH_API_BASE,
    _is_bot_mention,
    create_or_update_teams_ticket,
    graph_message_to_activity,
    graph_reply_to_activity,
    handle_teams_mention,
    handle_teams_message,
    is_shared_membership_type,
    parse_teams_root_message_id,
    post_help_card,
    post_teams_channel_message_via_graph,
)
from products.conversations.backend.teams_attachments import extract_teams_graph_images
from products.conversations.backend.teams_formatting import build_teams_reply_html

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:teams:event:"


def is_duplicate_teams_event(activity_id: str) -> bool:
    """Atomic Redis-backed dedup keyed on Bot Framework ``activity.id``.

    Used both by ``process_teams_event`` (after dispatch) and by the webhook
    handler (before dispatch, for the welcome and help-reply paths). Bot
    Framework retries with the same ``activity.id`` for up to ~10 mins on
    5xx/timeouts, so any handler that produces side effects must guard.
    """
    key = f"{SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX}{activity_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


@shared_task(
    name="products.conversations.backend.tasks.send_teams_help",
    bind=True,
    ignore_result=True,
    max_retries=2,
    default_retry_delay=5,
)
def send_teams_help(self, activity: dict[str, Any], reply: bool = False) -> None:
    """Post the help/welcome adaptive card (Teams Store cert 11.4.4.3).

    ``reply=True`` lands the card as a thread reply (response to a "Hi"/"Help"
    command); ``reply=False`` is the proactive welcome on install.
    """
    # Capture the tenant's serviceUrl as early as install — this is often the
    # only inbound activity a pure-ambient shared-channel tenant ever sends, and
    # the poller needs it to post confirmation cards / sync agent replies.
    tenant_id = ((activity.get("channelData") or {}).get("tenant") or {}).get("id") or ""
    try:
        store_teams_service_url(tenant_id, activity.get("serviceUrl") or "")
    except Exception:
        pass

    try:
        ok = post_help_card(
            activity,
            log_prefix="teams_help_reply" if reply else "teams_welcome",
            reply=reply,
        )
    except Exception as exc:
        logger.exception("supporthog_teams_help_failed", error=str(exc), reply=reply)
        raise cast(Any, self).retry(exc=exc)
    if not ok:
        raise cast(Any, self).retry(exc=Exception("teams_help_card_post_failed"))


@shared_task(
    name="products.conversations.backend.tasks.process_teams_event",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def process_teams_event(activity: dict[str, Any], tenant_id: str, activity_id: str = "") -> None:
    """Process an inbound Teams Bot Framework activity."""

    if activity_id and is_duplicate_teams_event(activity_id):
        logger.info("supporthog_teams_event_duplicate_skipped", activity_id=activity_id)
        return

    config = (
        TeamConversationsTeamsConfig.objects.filter(teams_tenant_id=tenant_id, teams_graph_access_token__isnull=False)
        .select_related("team")
        .first()
    )
    if not config:
        logger.warning("supporthog_teams_no_team", tenant_id=tenant_id)
        return

    team = config.team
    support_settings = team.conversations_settings or {}
    if not support_settings.get("teams_enabled"):
        logger.info("supporthog_teams_not_configured", team_id=team.id, tenant_id=tenant_id)
        return

    # Capture the tenant's Bot Framework serviceUrl from any inbound activity so
    # the shared-channel poller (which has no inbound activity) can post
    # confirmation cards and route agent replies for polled tickets.
    try:
        store_teams_service_url(tenant_id, activity.get("serviceUrl") or "")
    except Exception:
        logger.warning("store_teams_service_url_failed", team_id=team.id, tenant_id=tenant_id)

    try:
        if _is_bot_mention(activity):
            handle_teams_mention(activity, team, tenant_id)
        else:
            handle_teams_message(activity, team, tenant_id)
    except Exception as e:
        logger.exception("supporthog_teams_event_handler_failed", error=str(e))
        raise cast(Any, process_teams_event).retry(exc=e)


@shared_task(
    name="products.conversations.backend.tasks.post_reply_to_teams",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def post_reply_to_teams(
    ticket_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
    author_name: str,
    teams_service_url: str,
    teams_conversation_id: str,
) -> None:
    """Post a support agent's reply to the corresponding Teams conversation thread."""
    if not is_trusted_teams_service_url(teams_service_url):
        logger.warning("teams_reply_untrusted_service_url", ticket_id=ticket_id, service_url=teams_service_url)
        return

    if not Team.objects.filter(id=team_id).exists():
        logger.warning("teams_reply_team_not_found", team_id=team_id)
        return

    try:
        bot_token = get_bot_framework_token()
        bot_from_id = get_bot_from_id()
    except ValueError:
        logger.warning("teams_reply_no_bot_token", team_id=team_id)
        return

    reply_html = build_teams_reply_html(rich_content, content, author_name)
    display_text = f"{author_name}: {content[:200]}" if author_name else content[:200]

    payload: dict[str, Any] = {
        "type": "message",
        "from": {"id": bot_from_id},
        "conversation": {"id": teams_conversation_id},
        "text": reply_html,
        # Teams accepts only "plain", "markdown", or "xml" for textFormat — not "html".
        # With "markdown", Teams passes through the common HTML tags we emit
        # (<b>, <i>, <a>, <ul>, <li>, <p>, <br>, <code>, <pre>, <img>).
        "textFormat": "markdown",
        "summary": display_text,
    }

    encoded_conversation_id = quote(teams_conversation_id, safe="")
    url = f"{teams_service_url.rstrip('/')}/v3/conversations/{encoded_conversation_id}/activities"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 401:
            invalidate_bot_framework_token()
        if resp.status_code not in (200, 201):
            logger.warning(
                "teams_reply_post_failed",
                ticket_id=ticket_id,
                status=resp.status_code,
                body=resp.text[:500],
                url=url,
            )
            raise cast(Any, post_reply_to_teams).retry(
                exc=Exception(f"Teams reply failed with status {resp.status_code}")
            )

        logger.info("teams_reply_posted", ticket_id=ticket_id, conversation_id=teams_conversation_id)
    except requests.RequestException as e:
        logger.exception("teams_reply_post_error", ticket_id=ticket_id, error=str(e))
        raise cast(Any, post_reply_to_teams).retry(exc=e)


@shared_task(
    name="products.conversations.backend.tasks.post_reply_to_teams_via_graph",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def post_reply_to_teams_via_graph(
    ticket_id: str,
    team_id: int,
    teams_team_id: str,
    channel_id: str,
    root_message_id: str,
    content: str,
    rich_content: dict | None,
    author_name: str,
) -> None:
    """Post a support agent's reply into a shared Teams channel thread via Graph.

    Shared channels can't be written to over the bot connector, so replies go through
    Graph with the delegated admin token (same path the poller reads with).
    """
    team = Team.objects.filter(id=team_id).first()
    if not team:
        logger.warning("teams_graph_reply_team_not_found", team_id=team_id)
        return

    reply_html = build_teams_reply_html(rich_content, content, author_name)

    status, _message_id = post_teams_channel_message_via_graph(
        team=team,
        teams_team_id=teams_team_id,
        channel_id=channel_id,
        html=reply_html,
        reply_to_message_id=root_message_id,
        log_context={"ticket_id": ticket_id},
    )
    if status in (200, 201):
        logger.info("teams_graph_reply_posted", ticket_id=ticket_id, channel_id=channel_id)
        return

    # Retry only transient failures (network/no-token=0, throttling, 5xx). Permanent
    # ones — 401/403 (token/consent), 404 (thread gone), 400 — won't self-heal and
    # would just burn the retry budget, so log and drop.
    if status == 0 or status == 429 or status >= 500:
        raise cast(Any, post_reply_to_teams_via_graph).retry(
            exc=Exception(f"Teams Graph reply transient failure (status {status})")
        )
    logger.warning("teams_graph_reply_permanent_failure", ticket_id=ticket_id, status=status)


def _shared_channel_entries(support_settings: dict) -> list[dict]:
    """Configured channels the poller pulls (shared/unknownFutureValue, not standard/private)."""
    entries = support_settings.get("teams_channels")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and is_shared_membership_type(e.get("membership_type"))]


def _parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


# Bound the work per invocation so priming a long-lived channel (the first delta
# walk returns the channel's full history before the deltaLink) can't hammer Graph
# in a single run. Remaining pages resume on subsequent every-minute runs.
TEAMS_DELTA_MAX_PAGES_PER_RUN = 20
TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS = 30
TEAMS_REPLIES_MAX_PAGES_PER_TICKET = 5
# Graph list-replies caps $top at 50; larger values return 400 Bad Request.
TEAMS_REPLIES_PAGE_SIZE = 50
# Cap the number of tickets whose threads we poll per channel per run.
# Oldest-synced tickets are polled first so the sweep round-robins through
# the backlog across successive every-minute runs.
TEAMS_REPLIES_MAX_TICKETS_PER_CHANNEL = 20
# Only poll threads on tickets created within this window.
TEAMS_REPLIES_TICKET_AGE_DAYS = 30
# Re-scan a small window behind the watermark so replies aren't silently dropped when
# Graph's createdDateTime and our stored watermark disagree by a few seconds (clock skew
# between the polling worker and Graph). Dedup downstream makes the overlap harmless.
TEAMS_REPLIES_WATERMARK_LOOKBACK = timedelta(minutes=5)
# Safety cap on delta-triggered reply fetches per run. Delta only surfaces threads with
# fresh activity (so this is naturally traffic-bounded), but a pathological burst across
# many threads shouldn't fan out into unbounded Graph /replies calls in a single run.
TEAMS_REPLIES_MAX_DELTA_TRIGGERED_PER_CHANNEL = 50


def _sync_one_ticket_thread_replies(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    ticket: Ticket,
) -> None:
    """Ingest new thread replies for one shared-channel ticket via Graph."""
    root_message_id = parse_teams_root_message_id(ticket.teams_conversation_id)
    if not root_message_id:
        logger.debug(
            "poll_teams_shared_channel_replies_no_root",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )
        return

    raw_watermark = ticket.teams_thread_replies_synced_at or ticket.created_at
    watermark = raw_watermark - TEAMS_REPLIES_WATERMARK_LOOKBACK
    latest_synced_at = ticket.teams_thread_replies_synced_at

    url: str | None = (
        f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}/messages/{root_message_id}/replies"
        f"?$top={TEAMS_REPLIES_PAGE_SIZE}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    pages = 0
    replies_fetched = 0
    # "matched" = reply resolved to this ticket (covers both new comments and dedup
    # hits); create_or_update_teams_ticket doesn't distinguish, so we don't claim to.
    replies_matched = 0

    while url and pages < TEAMS_REPLIES_MAX_PAGES_PER_TICKET:
        pages += 1
        resp = requests.get(url, headers=headers, timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS)

        if resp.status_code in (401, 402, 403, 404, 429):
            logger.warning(
                "poll_teams_shared_channel_replies_denied",
                team_id=team.id,
                channel_id=channel_id,
                ticket_id=str(ticket.id),
                status=resp.status_code,
            )
            return
        if resp.status_code != 200:
            logger.warning(
                "poll_teams_shared_channel_replies_error",
                team_id=team.id,
                channel_id=channel_id,
                ticket_id=str(ticket.id),
                root_message_id=root_message_id,
                status=resp.status_code,
                body=resp.text[:500],
            )
            return

        data = resp.json()
        replies = data.get("value") or []
        replies_fetched += len(replies)

        page_had_failure = False
        for reply in replies:
            msg_created = _parse_graph_datetime(reply.get("createdDateTime"))
            if msg_created and msg_created < watermark:
                continue

            activity = graph_reply_to_activity(reply, channel_id, root_message_id, service_url)
            if activity is None:
                continue

            reply_images = extract_teams_graph_images(reply, team, teams_team_id, channel_id, token)
            try:
                result = create_or_update_teams_ticket(
                    team=team,
                    activity=activity,
                    tenant_id=tenant_id,
                    is_thread_reply=True,
                    attachments=reply_images,
                )
            except Exception:
                logger.exception(
                    "poll_teams_shared_channel_reply_ingest_failed",
                    team_id=team.id,
                    channel_id=channel_id,
                    ticket_id=str(ticket.id),
                )
                page_had_failure = True
                continue

            if result:
                replies_matched += 1
            if result and msg_created and (latest_synced_at is None or msg_created > latest_synced_at):
                latest_synced_at = msg_created

        if page_had_failure:
            break

        url = data.get("@odata.nextLink")

    if replies_fetched:
        logger.info(
            "poll_teams_shared_channel_replies_synced",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
            root_message_id=root_message_id,
            replies_fetched=replies_fetched,
            replies_matched=replies_matched,
            watermark=raw_watermark.isoformat(),
        )

    new_watermark = latest_synced_at or timezone.now()
    if new_watermark != ticket.teams_thread_replies_synced_at:
        Ticket.objects.filter(id=ticket.id, team=team).update(teams_thread_replies_synced_at=new_watermark)


def _sync_ticket_thread_replies_safe(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    ticket: Ticket,
) -> None:
    """Run ``_sync_one_ticket_thread_replies`` with the standard error handling."""
    try:
        _sync_one_ticket_thread_replies(
            team=team,
            tenant_id=tenant_id,
            token=token,
            teams_team_id=teams_team_id,
            channel_id=channel_id,
            service_url=service_url,
            ticket=ticket,
        )
    except requests.RequestException:
        logger.warning(
            "poll_teams_shared_channel_replies_network_error",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )
    except Exception:
        logger.exception(
            "poll_teams_shared_channel_replies_unexpected",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )


def _sync_shared_channel_thread_replies(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    surfaced_conversation_ids: set[str] | None = None,
) -> None:
    """Pull new thread replies for every Teams ticket in a shared channel.

    ``surfaced_conversation_ids`` are threads delta saw activity on this run; their
    tickets are always synced (on top of the round-robin selection) so a fresh reply
    is pulled the same minute even when the ticket isn't in the oldest-synced window.
    """
    sync = TeamConversationsTeamsChannelSync.objects.for_team(team.id).filter(channel_id=channel_id).first()
    if not sync or not sync.primed:
        logger.debug(
            "poll_teams_shared_channel_replies_not_primed",
            team_id=team.id,
            channel_id=channel_id,
            has_sync=bool(sync),
        )
        return

    age_cutoff = timezone.now() - timedelta(days=TEAMS_REPLIES_TICKET_AGE_DAYS)
    tickets = list(
        Ticket.objects.filter(
            team=team,
            channel_source=Channel.TEAMS,
            teams_channel_id=channel_id,
            created_at__gte=age_cutoff,
        )
        .exclude(teams_conversation_id__isnull=True)
        .exclude(teams_conversation_id="")
        .exclude(status=Status.RESOLVED)
        .order_by(F("teams_thread_replies_synced_at").asc(nulls_first=True))[:TEAMS_REPLIES_MAX_TICKETS_PER_CHANNEL]
    )

    selected_ids = {ticket.id for ticket in tickets}
    delta_triggered = 0
    if surfaced_conversation_ids:
        surfaced_tickets = (
            Ticket.objects.filter(
                team=team,
                channel_source=Channel.TEAMS,
                teams_channel_id=channel_id,
                teams_conversation_id__in=surfaced_conversation_ids,
            )
            .exclude(status=Status.RESOLVED)
            .exclude(id__in=selected_ids)
            .order_by(F("teams_thread_replies_synced_at").asc(nulls_first=True))[
                :TEAMS_REPLIES_MAX_DELTA_TRIGGERED_PER_CHANNEL
            ]
        )
        for ticket in surfaced_tickets:
            tickets.append(ticket)
            delta_triggered += 1

    logger.debug(
        "poll_teams_shared_channel_replies_tickets_selected",
        team_id=team.id,
        channel_id=channel_id,
        tickets_selected=len(tickets),
        delta_triggered=delta_triggered,
    )

    for ticket in tickets:
        _sync_ticket_thread_replies_safe(
            team=team,
            tenant_id=tenant_id,
            token=token,
            teams_team_id=teams_team_id,
            channel_id=channel_id,
            service_url=service_url,
            ticket=ticket,
        )


def _poll_one_shared_channel(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
) -> set[str]:
    """Pull new top-level messages for one shared channel via Graph messages/delta.

    First run for a channel primes the delta cursor without ingesting (no history
    dump); subsequent runs map each new root message onto the existing ticket path.
    Idempotency is handled by ``create_or_update_teams_ticket`` (dedup on
    channel + normalized conversation id), so re-delivering a message is a no-op.

    Returns the set of conversation ids whose root message delta re-surfaced this run,
    so the caller can prioritize their thread-reply sync.
    """
    sync, created = TeamConversationsTeamsChannelSync.objects.for_team(team.id).get_or_create(
        channel_id=channel_id,
        defaults={"team": team, "teams_team_id": teams_team_id},
    )

    # On first encounter, verify via Graph that the channel is actually shared.
    # conversations_settings is client-mutable, so we don't trust its
    # membership_type — we confirm from the authoritative source before polling.
    # Graph returns "unknownFutureValue" for shared channels in some tenants, so we
    # reject only explicit standard/private channels rather than requiring "shared".
    if created:
        ch_resp = requests.get(
            f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS,
        )
        if ch_resp.status_code != 200 or not is_shared_membership_type(ch_resp.json().get("membershipType")):
            logger.warning(
                "poll_teams_shared_channel_not_shared",
                team_id=team.id,
                channel_id=channel_id,
                status=ch_resp.status_code,
            )
            sync.delete()
            return set()

    url: str | None = sync.delta_link or (
        f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}/messages/delta"
    )
    headers = {"Authorization": f"Bearer {token}"}

    new_delta_link: str | None = None
    latest_message_at: datetime | None = None
    pages = 0
    # Root messages delta re-surfaced this run (Graph bumps a root's lastModifiedDateTime
    # when a thread reply lands). Their tickets get a targeted reply sync below so the
    # reply is pulled the same minute, independent of the round-robin reply sweep.
    surfaced_conversation_ids: set[str] = set()

    while url and pages < TEAMS_DELTA_MAX_PAGES_PER_RUN:
        pages += 1
        resp = requests.get(url, headers=headers, timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS)

        if resp.status_code == 410:
            # Delta token expired/invalid: reset and re-prime on the next run.
            sync.delta_link = None
            sync.primed = False
            sync.last_polled_at = timezone.now()
            sync.save(update_fields=["delta_link", "primed", "last_polled_at", "updated_at"])
            logger.info("poll_teams_shared_channel_resync", team_id=team.id, channel_id=channel_id)
            return set()
        if resp.status_code == 429:
            logger.warning("poll_teams_shared_channel_throttled", team_id=team.id, channel_id=channel_id)
            return set()
        if resp.status_code in (401, 402, 403):
            # 401: token rejected (next run refreshes if stale). 402: metered/payment
            # gate. 403: lost channel membership / missing scope. Skip, don't crash.
            logger.warning(
                "poll_teams_shared_channel_denied",
                team_id=team.id,
                channel_id=channel_id,
                status=resp.status_code,
            )
            return set()
        if resp.status_code != 200:
            logger.warning(
                "poll_teams_shared_channel_error",
                team_id=team.id,
                channel_id=channel_id,
                status=resp.status_code,
            )
            return set()

        data = resp.json()
        messages = data.get("value") or []

        if sync.primed:
            for msg in messages:
                msg_created = _parse_graph_datetime(msg.get("createdDateTime"))
                if msg_created and (latest_message_at is None or msg_created > latest_message_at):
                    latest_message_at = msg_created
                activity = graph_message_to_activity(msg, channel_id, service_url)
                if activity is None:
                    continue
                conversation_id = (activity.get("conversation") or {}).get("id")
                if conversation_id:
                    surfaced_conversation_ids.add(conversation_id)
                images = extract_teams_graph_images(msg, team, teams_team_id, channel_id, token)
                try:
                    create_or_update_teams_ticket(
                        team=team,
                        activity=activity,
                        tenant_id=tenant_id,
                        is_thread_reply=False,
                        channel_detail=ChannelDetail.TEAMS_CHANNEL_MESSAGE,
                        # Shared channel: confirm via Graph (bot connector can't post here),
                        # reusing the token we already hold for the delta read.
                        graph_post_context={"teams_team_id": teams_team_id, "token": token},
                        attachments=images,
                    )
                except Exception:
                    logger.exception(
                        "poll_teams_shared_channel_ingest_failed",
                        team_id=team.id,
                        channel_id=channel_id,
                    )

        delta_link = data.get("@odata.deltaLink")
        next_link = data.get("@odata.nextLink")
        if delta_link:
            new_delta_link = delta_link
            url = None
        else:
            url = next_link

    update_fields = ["last_polled_at", "updated_at"]
    sync.last_polled_at = timezone.now()

    if new_delta_link:
        sync.delta_link = new_delta_link
        update_fields.append("delta_link")
        if not sync.primed:
            sync.primed = True
            update_fields.append("primed")
    elif url:
        # Hit the per-run page budget mid-walk; resume from this nextLink next run.
        sync.delta_link = url
        update_fields.append("delta_link")

    if latest_message_at and (sync.last_message_at is None or latest_message_at > sync.last_message_at):
        sync.last_message_at = latest_message_at
        update_fields.append("last_message_at")

    sync.save(update_fields=update_fields)

    # Delta only surfaces roots, never the replies themselves. A re-surfaced root signals
    # thread activity, so the caller passes these ids to the reply sweep to pull their
    # replies the same minute regardless of the round-robin selection.
    return surfaced_conversation_ids


@shared_task(
    name="products.conversations.backend.tasks.poll_team_shared_channels",
    ignore_result=True,
)
@skip_team_scope_audit
def poll_team_shared_channels(team_id: int) -> None:
    """Poll every configured shared channel for one team."""
    team = Team.objects.filter(id=team_id).first()
    if not team:
        return

    support_settings = team.conversations_settings or {}
    if not support_settings.get("teams_enabled"):
        return

    shared_channels = _shared_channel_entries(support_settings)
    if not shared_channels:
        return

    config = TeamConversationsTeamsConfig.objects.filter(team=team).first()
    tenant_id = config.teams_tenant_id if config else None
    if not tenant_id:
        logger.warning("poll_teams_shared_channels_no_tenant", team_id=team_id)
        return

    try:
        token = get_graph_token(team)
    except ValueError:
        logger.warning("poll_teams_shared_channels_no_token", team_id=team_id)
        return

    # serviceUrl is captured from inbound webhook activities (install/mention).
    # Empty until then: polled tickets still get created, but confirmation cards
    # and agent-reply sync stay dormant until the first inbound activity fills it.
    service_url = (config.teams_service_url or "") if config else ""

    for entry in shared_channels:
        channel_id = entry.get("channel_id")
        teams_team_id = entry.get("team_id")
        if not channel_id or not teams_team_id:
            continue
        try:
            surfaced_conversation_ids = _poll_one_shared_channel(
                team=team,
                tenant_id=tenant_id,
                token=token,
                teams_team_id=teams_team_id,
                channel_id=channel_id,
                service_url=service_url,
            )
            _sync_shared_channel_thread_replies(
                team=team,
                tenant_id=tenant_id,
                token=token,
                teams_team_id=teams_team_id,
                channel_id=channel_id,
                service_url=service_url,
                surfaced_conversation_ids=surfaced_conversation_ids,
            )
        except requests.RequestException:
            logger.warning("poll_teams_shared_channel_network_error", team_id=team_id, channel_id=channel_id)
        except Exception:
            logger.exception("poll_teams_shared_channel_unexpected", team_id=team_id, channel_id=channel_id)


@shared_task(
    name="products.conversations.backend.tasks.poll_teams_shared_channels",
    ignore_result=True,
)
@skip_team_scope_audit
def poll_teams_shared_channels() -> None:
    """Fan out per-team shared-channel polling.

    Shared/private Teams channels never push ambient (non-@mention) messages over
    the bot webhook, so we pull them from Graph on a schedule. One subtask per team
    keeps a slow or rate-limited tenant from blocking the others.
    """
    configs = (
        TeamConversationsTeamsConfig.objects.filter(teams_graph_access_token__isnull=False)
        .select_related("team")
        .only("team__id", "team__conversations_settings", "teams_tenant_id")
    )

    team_ids: list[int] = []
    for config in configs:
        support_settings = config.team.conversations_settings or {}
        if not support_settings.get("teams_enabled"):
            continue
        if _shared_channel_entries(support_settings):
            team_ids.append(config.team_id)

    for team_id in team_ids:
        poll_team_shared_channels.delay(team_id)

    if team_ids:
        logger.info("poll_teams_shared_channels_fanout", team_count=len(team_ids))
