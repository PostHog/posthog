"""Title, state, and type of a linked GitHub issue or PR, fetched through the project's GitHub integration."""

from collections.abc import Iterable
from datetime import timedelta

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration

from products.conversations.backend.models.ticket_github_link import (
    TicketGithubLink,
    TicketGithubLinkState,
    TicketGithubLinkType,
)

logger = structlog.get_logger(__name__)

# Links keep the title/state they were last synced with; the list endpoint refreshes anything older than
# this, a few at a time, so a ticket page stays roughly current without hammering GitHub.
METADATA_STALE_AFTER = timedelta(minutes=15)
MAX_REFRESHES_PER_REQUEST = 5


@frozen
class GithubLinkMetadata:
    title: str
    link_type: TicketGithubLinkType
    link_state: TicketGithubLinkState


def fetch_github_link_metadata(
    team_id: int, repo: str, number: int, *, github: GitHubIntegration | None = None
) -> GithubLinkMetadata | None:
    """Look the issue/PR up via a GitHub integration that can see ``repo``; None if none can or the call fails."""
    github = github or find_github_integration(team_id, repo)
    if github is None:
        return None
    try:
        payload = github.get_issue(repo, number)
    except Exception:
        # Any failure (not found, rate-limited, egress budget, network) just leaves the link without metadata.
        logger.info("conversations_github_link_metadata_failed", repo=repo, number=number, exc_info=True)
        return None
    return _metadata_from_issue_payload(payload)


def find_github_integration(team_id: int, repo: str) -> GitHubIntegration | None:
    return GitHubIntegration.first_for_team_repository(team_id, repo, source="conversations", priority=Priority.NORMAL)


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


def refresh_stale_github_links(team_id: int, links: Iterable[TicketGithubLink]) -> None:
    """Re-fetch title/state for links whose metadata is missing or older than METADATA_STALE_AFTER.

    Bounded to MAX_REFRESHES_PER_REQUEST GitHub lookups, resolving the integration once per repo.
    """
    cutoff = timezone.now() - METADATA_STALE_AFTER
    stale = [link for link in links if link.metadata_synced_at is None or link.metadata_synced_at < cutoff]
    if not stale:
        return

    integrations: dict[str, GitHubIntegration | None] = {}
    for link in stale[:MAX_REFRESHES_PER_REQUEST]:
        if link.repo not in integrations:
            integrations[link.repo] = find_github_integration(team_id, link.repo)
        github = integrations[link.repo]
        # Stamp the sync time even with no usable integration so the next page view doesn't re-probe.
        metadata = fetch_github_link_metadata(team_id, link.repo, link.number, github=github) if github else None
        apply_github_link_metadata(link, metadata)
        link.save(update_fields=["title", "link_type", "link_state", "metadata_synced_at"])
