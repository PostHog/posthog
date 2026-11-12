from enum import StrEnum

from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import MetricListFilters
from ..facade.enums import CertificationStatus, MetricStatus, RelationshipStatus
from ..models import RelationshipProposal, TableCertification
from .analytics import certification_target_name
from .certifications import certifications_for_team
from .metrics import metrics_for_team, metrics_visible_to_user
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
class PendingReviewCounts:
    metrics: int
    relationships: int
    certifications: int


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


def _proposed_relationships(team: Team) -> QuerySet[RelationshipProposal]:
    return relationships_for_team(team).filter(status=RelationshipStatus.PROPOSED)


def _proposed_certifications(team: Team) -> QuerySet[TableCertification]:
    return certifications_for_team(team).filter(status=CertificationStatus.PROPOSED)


def _relationships_group(team: Team, sample_size: int) -> PendingGroup:
    proposed = _proposed_relationships(team)
    oldest_first = proposed.order_by("created_at")[:sample_size]
    return PendingGroup(
        kind=PendingKind.RELATIONSHIPS,
        noun="relationship",
        count=proposed.count(),
        sample_names=[f"{proposal.source_table_name} to {proposal.joining_table_name}" for proposal in oldest_first],
    )


def _certifications_group(team: Team, sample_size: int) -> PendingGroup:
    proposed = _proposed_certifications(team)
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


def pending_review_counts(team: Team, user: User, user_access_control: UserAccessControl) -> PendingReviewCounts:
    """How many items wait in each review queue, counted as the caller's list of that queue shows them."""
    proposed_metrics = metrics_visible_to_user(
        team, user, user_access_control, MetricListFilters(status=MetricStatus.PROPOSED)
    )
    return PendingReviewCounts(
        metrics=proposed_metrics.count(),
        relationships=_proposed_relationships(team).count(),
        certifications=_proposed_certifications(team).count(),
    )


@frozen
class PendingReviewBuild:
    reviews: dict[int, TeamPendingReview]
    failed_team_ids: list[int]


def build_org_pending_reviews(teams: list[Team], sample_size: int = DEFAULT_SAMPLE_SIZE) -> PendingReviewBuild:
    """Teams with something to review, keyed by team id, and the teams that raised. Raises if all raised."""
    reviews: dict[int, TeamPendingReview] = {}
    failed_team_ids: list[int] = []
    for team in teams:
        try:
            review = build_team_pending_review(team, sample_size)
        except Exception as e:
            logger.warning("failed to build data catalog pending review", team_id=team.id, error=str(e))
            capture_exception(e, {"team_id": team.id})
            failed_team_ids.append(team.id)
            continue
        if review is not None:
            reviews[team.id] = review
    if teams and len(failed_team_ids) == len(teams):
        raise RuntimeError("Data catalog digest: no project's pending review could be built")
    return PendingReviewBuild(reviews=reviews, failed_team_ids=failed_team_ids)
