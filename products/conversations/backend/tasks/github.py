"""GitHub Issues inbound events, outbound replies, and ticket creation."""

from typing import Any, cast

from django.core.cache import cache
from django.db import IntegrityError, models, transaction

import requests
import structlog
from celery import shared_task

from posthog.comment.formatting import rich_content_to_markdown
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.comment import Comment as CommentModel
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit

from products.conversations.backend.events import capture_ticket_status_changed
from products.conversations.backend.models import GithubCommentMapping
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:github:event:"


def _is_duplicate_github_event(delivery_id: str) -> bool:
    key = f"{SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}"
    return cache.get(key) is not None


def _mark_github_event_processed(delivery_id: str) -> None:
    key = f"{SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}"
    cache.set(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


def _find_github_ticket(team_id: int, repo: str, issue_number: int) -> Ticket | None:
    return Ticket.objects.filter(
        team_id=team_id,
        github_repo=repo,
        github_issue_number=issue_number,
    ).first()


def _get_or_create_github_ticket(team: Team, repo: str, issue_number: int, payload: dict[str, Any]) -> Ticket:
    """Find or create a ticket for a GitHub issue, safe against concurrent calls.

    Uses transaction.atomic() + the DB unique constraint
    posthog_con_github_issue_uniq to guarantee exactly one ticket per issue.
    """
    existing = _find_github_ticket(team.id, repo, issue_number)
    if existing:
        return existing

    issue = payload.get("issue", {})
    sender = payload.get("sender", {})
    issue_author = issue.get("user", {}).get("login", sender.get("login", ""))
    title = issue.get("title", "")

    try:
        with transaction.atomic():
            ticket = Ticket.objects.create_with_number(
                team=team,
                channel_source="github",
                channel_detail="github_issue",
                widget_session_id="",
                distinct_id=f"github:{issue_author}" if issue_author else "github:unknown",
                status=Status.NEW,
                anonymous_traits={"name": issue_author, "github_login": issue_author},
                github_repo=repo,
                github_issue_number=issue_number,
                unread_team_count=0,
                # Created from a signature-validated GitHub webhook — platform-attested identity.
                identity_verified=True,
            )

            if title:
                CommentModel.objects.create(
                    team=team,
                    scope="conversations_ticket",
                    item_id=str(ticket.id),
                    content=f"**{title}**",
                    item_context={"author_type": "customer", "is_private": False, "from_github": True},
                )

            return ticket
    except IntegrityError:
        existing = _find_github_ticket(team.id, repo, issue_number)
        if existing:
            return existing
        raise


@shared_task(
    name="products.conversations.backend.tasks.process_github_event",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def process_github_event(
    event_type: str,
    action: str,
    payload: dict[str, Any],
    delivery_id: str,
    team_id: int,
    repo: str,
) -> None:
    """Process an inbound GitHub webhook event for the Issues channel."""
    if delivery_id and _is_duplicate_github_event(delivery_id):
        logger.info("github_event_duplicate_skipped", delivery_id=delivery_id)
        return

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("github_event_team_not_found", team_id=team_id)
        return

    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("github_enabled"):
        return

    allowed_repos: list[str] = settings_dict.get("github_repos", [])
    if repo not in allowed_repos:
        logger.info("github_event_repo_not_monitored", repo=repo, team_id=team_id)
        return

    try:
        if event_type == "issues":
            _handle_github_issue_event(team, repo, action, payload)
        elif event_type == "issue_comment":
            _handle_github_comment_event(team, repo, action, payload)
    except Exception as e:
        logger.exception("github_event_handler_failed", event_type=event_type, action=action, error=str(e))
        raise cast(Any, process_github_event).retry(exc=e)

    if delivery_id:
        _mark_github_event_processed(delivery_id)


def _handle_github_issue_event(team: Team, repo: str, action: str, payload: dict[str, Any]) -> None:
    issue = payload.get("issue", {})
    issue_number = issue.get("number")
    if not issue_number:
        return

    if action == "opened":
        existing = _find_github_ticket(team.id, repo, issue_number)
        if existing:
            return

        ticket = _get_or_create_github_ticket(team, repo, issue_number, payload)

        # For "opened" events we have the full body — replace the title-only
        # comment that _get_or_create_github_ticket may have created with a
        # richer version including the issue body.
        sender = payload.get("sender", {})
        author_login = sender.get("login", "")
        title = issue.get("title", "")
        body = issue.get("body", "") or ""

        if body:
            first_comment = (
                CommentModel.objects.filter(team=team, scope="conversations_ticket", item_id=str(ticket.id))
                .order_by("created_at")
                .first()
            )
            if first_comment:
                first_comment.content = f"**{title}**\n\n{body}"[:50_000]
                first_comment.item_context = {
                    **(first_comment.item_context or {}),
                    "github_login": author_login,
                    "github_issue_title": title,
                }
                first_comment.save(update_fields=["content", "item_context"])

        ticket.unread_team_count = 1
        ticket.save(update_fields=["unread_team_count", "updated_at"])

    elif action in ("closed", "reopened"):
        existing = _find_github_ticket(team.id, repo, issue_number)
        if not existing:
            return

        # Reject stale/replayed payloads: skip if the issue event is older
        # than the ticket's last update (guards against replay after cache TTL)
        issue_updated_at = issue.get("updated_at")
        if issue_updated_at and existing.updated_at:
            try:
                from datetime import datetime

                event_ts = datetime.fromisoformat(issue_updated_at.replace("Z", "+00:00"))
                if event_ts < existing.updated_at:
                    logger.info(
                        "github_event_stale_status_change",
                        action=action,
                        ticket_id=str(existing.id),
                        event_ts=issue_updated_at,
                    )
                    return
            except (ValueError, TypeError):
                pass

        new_status = Status.RESOLVED if action == "closed" else Status.OPEN
        if existing.status == new_status:
            return

        old_status = existing.status
        existing.status = new_status
        existing.save(update_fields=["status", "updated_at"])
        try:
            capture_ticket_status_changed(existing, old_status, new_status, actor_type="external")
        except Exception:
            logger.exception("github_event_status_change_event_failed", ticket_id=str(existing.id))


def _handle_github_comment_event(team: Team, repo: str, action: str, payload: dict[str, Any]) -> None:
    if action != "created":
        return

    issue = payload.get("issue", {})
    comment_data = payload.get("comment", {})
    issue_number = issue.get("number")
    comment_id = comment_data.get("id")
    if not issue_number or not comment_id:
        return

    if GithubCommentMapping.objects.filter(github_comment_id=comment_id, team=team).exists():
        return

    # Comments posted via our GitHub App installation token carry
    # performed_via_github_app — skip these to avoid echoing our own replies.
    # The post_reply_to_github task will record the mapping once it completes.
    if comment_data.get("performed_via_github_app"):
        return

    ticket = _find_github_ticket(team.id, repo, issue_number)
    if not ticket:
        ticket = _get_or_create_github_ticket(team, repo, issue_number, payload)

    comment_author = comment_data.get("user", {}).get("login", "")
    body = comment_data.get("body", "") or ""

    item_context: dict[str, Any] = {
        "author_type": "customer",
        "is_private": False,
        "from_github": True,
        "github_login": comment_author,
        "github_comment_id": comment_id,
    }

    try:
        with transaction.atomic():
            comment = CommentModel.objects.create(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=body[:50_000],
                item_context=item_context,
            )

            GithubCommentMapping.objects.create(
                github_comment_id=comment_id,
                team=team,
                ticket=ticket,
                comment=comment,
            )
    except IntegrityError:
        # unique_github_comment_per_team — another worker already created this mapping
        return

    Ticket.objects.filter(id=ticket.id, team=team).update(
        unread_team_count=models.F("unread_team_count") + 1,
    )


@shared_task(
    name="products.conversations.backend.tasks.post_reply_to_github",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def post_reply_to_github(
    ticket_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
    author_name: str,
) -> None:
    """Post a support agent's reply to the corresponding GitHub issue."""
    from posthog.models.integration import GitHubIntegration

    try:
        ticket = Ticket.objects.get(id=ticket_id, team_id=team_id)
    except Ticket.DoesNotExist:
        logger.warning("github_reply_ticket_not_found", ticket_id=ticket_id)
        return

    if not ticket.github_repo or not ticket.github_issue_number:
        logger.warning("github_reply_missing_issue_info", ticket_id=ticket_id)
        return

    try:
        github = GitHubIntegration.first_for_team_repository(team_id, ticket.github_repo, source="conversations")
    except GitHubRateLimitError as e:
        # The access probe hit GitHub's limit — retry the reply later rather than dropping it.
        logger.warning("github_reply_rate_limited", ticket_id=ticket_id)
        raise cast(Any, post_reply_to_github).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    if not github:
        logger.warning("github_reply_no_integration", team_id=team_id, repo=ticket.github_repo)
        return

    if rich_content:
        reply_text = rich_content_to_markdown(rich_content, include_images=True)
    else:
        reply_text = content

    if author_name:
        reply_text = f"**{author_name}** replied:\n\n{reply_text}"

    try:
        resp = github.api_request(
            "POST",
            f"/repos/{ticket.github_repo}/issues/{ticket.github_issue_number}/comments",
            json_body={"body": reply_text},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                "github_reply_post_failed",
                ticket_id=ticket_id,
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise cast(Any, post_reply_to_github).retry(
                exc=Exception(f"GitHub reply failed with status {resp.status_code}")
            )

        # Record the comment ID so the inbound webhook handler skips it
        resp_data = resp.json()
        gh_comment_id = resp_data.get("id")
        if gh_comment_id:
            GithubCommentMapping.objects.get_or_create(
                github_comment_id=gh_comment_id,
                team_id=team_id,
                defaults={"ticket": ticket, "comment": None},
            )

        logger.info("github_reply_posted", ticket_id=ticket_id, repo=ticket.github_repo)
    except GitHubRateLimitError as e:
        logger.warning("github_reply_rate_limited", ticket_id=ticket_id)
        raise cast(Any, post_reply_to_github).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    except (GitHubIntegrationError, requests.RequestException) as e:
        logger.exception("github_reply_post_error", ticket_id=ticket_id, error=str(e))
        raise cast(Any, post_reply_to_github).retry(exc=e)


@shared_task(
    name="products.conversations.backend.tasks.create_github_issue",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def create_github_issue(
    team_id: int,
    integration_id: int,
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict[str, Any] | None:
    """Create a GitHub issue and a linked Ticket."""
    from posthog.models.integration import GitHubIntegration, Integration

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("github_create_issue_team_not_found", team_id=team_id)
        return None

    try:
        integration = Integration.objects.get(id=integration_id, team=team, kind="github")
    except Integration.DoesNotExist:
        logger.warning("github_create_issue_integration_not_found", integration_id=integration_id)
        return None

    github = GitHubIntegration(integration, source="conversations")

    try:
        issue_data = github.create_issue({"title": title, "body": body, "repository": repo, "labels": labels})
    except GitHubRateLimitError as e:
        logger.warning("github_create_issue_rate_limited", repo=repo)
        raise cast(Any, create_github_issue).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    except GitHubIntegrationError as e:
        logger.exception("github_create_issue_failed", repo=repo, error=str(e))
        raise cast(Any, create_github_issue).retry(exc=e)

    issue_number = issue_data.get("number")

    ticket = Ticket.objects.create_with_number(
        team=team,
        channel_source="github",
        channel_detail="github_issue",
        widget_session_id="",
        distinct_id="",
        status=Status.OPEN,
        github_repo=repo,
        github_issue_number=issue_number,
        # Outbound issue opened by the team — there's no external party whose identity we verified,
        # so leave it unknown rather than claiming a verification that never happened.
        identity_verified=None,
    )

    CommentModel.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=f"**{title}**\n\n{body}" if body else f"**{title}**",
        item_context={"author_type": "customer", "is_private": False, "from_github": True},
    )

    logger.info("github_issue_created", ticket_id=str(ticket.id), repo=repo, issue_number=issue_number)
    return {"ticket_id": str(ticket.id), "issue_number": issue_number}
