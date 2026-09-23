from enum import StrEnum

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from ..facade.enums import CertificationStatus, MetricStatus, RelationshipStatus
from .analytics import certification_target_name
from .certifications import certifications_for_team
from .metrics import metrics_for_team
from .relationships import relationships_for_team

logger = structlog.get_logger(__name__)

DEFAULT_SAMPLE_SIZE = 5


class PendingKind(StrEnum):
    """A review queue in the data catalog. Each value is also the scene tab that opens the queue."""

    METRICS = "metrics"
    RELATIONSHIPS = "relationships"
    CERTIFICATIONS = "certifications"


@frozen
class PendingGroup:
    kind: PendingKind
    noun: str
    count: int
    sample_names: list[str]


@frozen
class TeamPendingReview:
    team_id: int
    team_name: str
    groups: list[PendingGroup]
    total: int


def _metrics_group(team: Team, sample_size: int) -> PendingGroup:
    proposed = metrics_for_team(team).filter(status=MetricStatus.PROPOSED)
    oldest_first = proposed.order_by("created_at")[:sample_size]
    return PendingGroup(
        kind=PendingKind.METRICS,
        noun="metric",
        count=proposed.count(),
        sample_names=[metric.display_name or metric.name for metric in oldest_first],
    )


def _relationships_group(team: Team, sample_size: int) -> PendingGroup:
    proposed = relationships_for_team(team).filter(status=RelationshipStatus.PROPOSED)
    oldest_first = proposed.order_by("created_at")[:sample_size]
    return PendingGroup(
        kind=PendingKind.RELATIONSHIPS,
        noun="relationship",
        count=proposed.count(),
        sample_names=[f"{proposal.source_table_name} to {proposal.joining_table_name}" for proposal in oldest_first],
    )


def _certifications_group(team: Team, sample_size: int) -> PendingGroup:
    proposed = certifications_for_team(team).filter(status=CertificationStatus.PROPOSED)
    oldest_first = proposed.order_by("created_at")[:sample_size]
    return PendingGroup(
        kind=PendingKind.CERTIFICATIONS,
        noun="certification",
        count=proposed.count(),
        sample_names=[certification_target_name(cert) for cert in oldest_first],
    )


def build_team_pending_review(team: Team, sample_size: int = DEFAULT_SAMPLE_SIZE) -> TeamPendingReview | None:
    """What a team still has to review, or None when every queue is empty.

    Samples are the oldest items first, so the ones that have waited longest are the ones named.
    """
    groups = [
        group
        for group in (
            _metrics_group(team, sample_size),
            _relationships_group(team, sample_size),
            _certifications_group(team, sample_size),
        )
        if group.count
    ]
    if not groups:
        return None
    return TeamPendingReview(
        team_id=team.id,
        team_name=team.name,
        groups=groups,
        total=sum(group.count for group in groups),
    )


def build_org_pending_reviews(
    teams: list[Team], sample_size: int = DEFAULT_SAMPLE_SIZE
) -> dict[int, TeamPendingReview]:
    """Teams with something to review, keyed by team id. A team that raises is logged and left out."""
    reviews: dict[int, TeamPendingReview] = {}
    for team in teams:
        try:
            review = build_team_pending_review(team, sample_size)
        except Exception as e:
            logger.warning("failed to build data catalog pending review", team_id=team.id, error=str(e))
            capture_exception(e, {"team_id": team.id})
            continue
        if review is not None:
            reviews[team.id] = review
    return reviews
