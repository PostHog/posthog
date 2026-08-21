"""Title, state, and type of a linked GitHub issue or PR, fetched through the project's GitHub integrations."""

from collections.abc import Iterable
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

from products.conversations.backend.models.ticket_github_link import (
    TicketGithubLink,
    TicketGithubLinkState,
    TicketGithubLinkType,
)

logger = structlog.get_logger(__name__)

# Links keep the title/state they were last synced with. Listing a ticket's links schedules a background
# refresh for anything older than this, so the panel stays roughly current without GitHub calls on the
# request path.
METADATA_STALE_AFTER = timedelta(minutes=15)
MAX_REFRESHES_PER_RUN = 20
# The lookup runs inside the create request (so the title shows immediately), so it is bounded tightly:
# one short attempt per integration, no transient retry.
GITHUB_LOOKUP_TIMEOUT_SECONDS = 5


@frozen
class GithubLinkMetadata:
    title: str
    link_type: TicketGithubLinkType
    link_state: TicketGithubLinkState


def fetch_github_link_metadata(team_id: int, repo: str, number: int) -> GithubLinkMetadata | None:
    """Ask each GitHub integration on the team for the issue; None if none can see it or GitHub fails.

    GitHub answers 404 for repositories an installation cannot access, so the lookup doubles as the
    access probe and the next integration is tried. Any other failure (rate limit, egress budget,
    network, unexpected payload) leaves the link without metadata rather than failing the request.
    """
    try:
        for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
            github = GitHubIntegration(integration, source="conversations", priority=Priority.NORMAL)
            try:
                payload = github.get_issue(repo, number, timeout=GITHUB_LOOKUP_TIMEOUT_SECONDS, retry_transient=False)
            except GitHubIntegrationError as e:
                if e.status_code == 404:
                    continue
                raise
            return _metadata_from_issue_payload(payload)
    except Exception:
        logger.info("conversations_github_link_metadata_failed", repo=repo, number=number, exc_info=True)
    return None


def _metadata_from_issue_payload(payload: dict) -> GithubLinkMetadata | None:
    title = payload.get("title")
    if not isinstance(title, str):
        return None
    pull_request = payload.get("pull_request")
    is_pull_request = isinstance(pull_request, dict)
    merged = isinstance(pull_request, dict) and bool(pull_request.get("merged_at"))
    if merged:
        state = TicketGithubLinkState.MERGED
    elif payload.get("state") == "closed":
        state = TicketGithubLinkState.CLOSED
    else:
        state = TicketGithubLinkState.OPEN
    return GithubLinkMetadata(
        title=title[:512],
        link_type=TicketGithubLinkType.PULL_REQUEST if is_pull_request else TicketGithubLinkType.ISSUE,
        link_state=state,
    )


def apply_github_link_metadata(link: TicketGithubLink, metadata: GithubLinkMetadata | None) -> None:
    """Copy fetched metadata onto the link in memory; a None fetch only stamps the sync time."""
    if metadata is not None:
        link.title = metadata.title
        link.link_type = metadata.link_type
        link.link_state = metadata.link_state
    link.metadata_synced_at = timezone.now()


def is_github_link_stale(link: TicketGithubLink) -> bool:
    return link.metadata_synced_at is None or link.metadata_synced_at < timezone.now() - METADATA_STALE_AFTER


def has_stale_github_links(links: Iterable[TicketGithubLink]) -> bool:
    return any(is_github_link_stale(link) for link in links)


def refresh_stale_github_links(team_id: int, ticket_id: str) -> int:
    """Re-fetch title/state for the ticket's links whose metadata is missing or older than METADATA_STALE_AFTER.

    Meant for a background task: each link costs up to one GitHub call per integration. Returns the
    number of links refreshed. The sync time is stamped even when no integration can see the repo, so a
    link is probed at most once per staleness window.
    """
    cutoff = timezone.now() - METADATA_STALE_AFTER
    stale = list(
        TicketGithubLink.objects.filter(ticket_id=ticket_id)
        .filter(Q(metadata_synced_at__isnull=True) | Q(metadata_synced_at__lt=cutoff))
        .order_by("created_at")[:MAX_REFRESHES_PER_RUN]
    )
    for link in stale:
        apply_github_link_metadata(link, fetch_github_link_metadata(team_id, link.repo, link.number))
        link.save(update_fields=["title", "link_type", "link_state", "metadata_synced_at"])
    return len(stale)
