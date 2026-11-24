from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from django.db.models import Expression, F, Model, QuerySet
from django.db.models.functions import Coalesce

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import MetricListFilters
from ..facade.enums import CertificationStatus, MetricStatus, RelationshipStatus
from ..models import Metric, RelationshipProposal, TableCertification
from .analytics import certification_target_name
from .certifications import certifications_for_team
from .metrics import cached_denied_tables, metrics_for_team, metrics_visible_to_user
from .relationships import relationships_for_team

logger = structlog.get_logger(__name__)

DEFAULT_SAMPLE_SIZE = 5
CREATED_AT = F("created_at")


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
    new_count: int = 0


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


def _group[ModelT: Model](
    kind: PendingKind,
    noun: str,
    proposed: QuerySet[ModelT],
    sample_name: Callable[[ModelT], str],
    sample_size: int,
    new_since: datetime | None,
    entered_review: Expression | F = CREATED_AT,
) -> PendingGroup:
    oldest_first = proposed.order_by("created_at")[:sample_size]
    return PendingGroup(
        kind=kind,
        noun=noun,
        count=proposed.count(),
        sample_names=[sample_name(item) for item in oldest_first],
        new_count=proposed.alias(entered_review=entered_review).filter(entered_review__gte=new_since).count()
        if new_since
        else 0,
    )


def _metrics_group(proposed: QuerySet[Metric], sample_size: int, new_since: datetime | None) -> PendingGroup:
    return _group(
        PendingKind.METRICS,
        "metric",
        proposed,
        lambda metric: metric.display_name or metric.name,
        sample_size,
        new_since,
        entered_review=Coalesce("proposed_at", "created_at"),
    )


def _proposed_metrics(team: Team) -> QuerySet[Metric]:
    return metrics_for_team(team).filter(status=MetricStatus.PROPOSED)


def _denied_tables_for_proposed_metrics(team: Team, user: User, user_access_control: UserAccessControl) -> set[str]:
    proposed_table_readers = _proposed_metrics(team).exclude(referenced_table_names=[])
    return cached_denied_tables(
        team,
        user,
        user_access_control,
        referenced_tables_by_metric={
            str(metric_id): sorted(table_names)
            for metric_id, table_names in proposed_table_readers.values_list("id", "referenced_table_names")
        },
    )


def _proposed_relationships(team: Team) -> QuerySet[RelationshipProposal]:
    return relationships_for_team(team).filter(status=RelationshipStatus.PROPOSED)


def _proposed_certifications(team: Team) -> QuerySet[TableCertification]:
    return certifications_for_team(team).filter(status=CertificationStatus.PROPOSED)


def _relationships_group(team: Team, sample_size: int, new_since: datetime | None) -> PendingGroup:
    return _group(
        PendingKind.RELATIONSHIPS,
        "relationship",
        _proposed_relationships(team),
        lambda proposal: f"{proposal.source_table_name} to {proposal.joining_table_name}",
        sample_size,
        new_since,
    )


def _certifications_group(team: Team, sample_size: int, new_since: datetime | None) -> PendingGroup:
    return _group(
        PendingKind.CERTIFICATIONS,
        "certification",
        _proposed_certifications(team),
        certification_target_name,
        sample_size,
        new_since,
    )


def build_team_pending_review(
    team: Team, sample_size: int = DEFAULT_SAMPLE_SIZE, new_since: datetime | None = None
) -> TeamPendingReview | None:
    """What a team still has to review, or None when every queue is empty.

    Samples are the oldest items first, so the ones that have waited longest are the ones named.
    """
    groups = [
        group
        for group in (
            _metrics_group(_proposed_metrics(team), sample_size, new_since),
            _relationships_group(team, sample_size, new_since),
            _certifications_group(team, sample_size, new_since),
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
    """How many items wait in each review queue, as the caller's lists show them, up to ten minutes behind an access change."""
    return PendingReviewCounts(
        metrics=_visible_proposed_metrics(team, user, user_access_control).count(),
        relationships=_proposed_relationships(team).count(),
        certifications=_proposed_certifications(team).count(),
    )


def groups_visible_to(
    review: TeamPendingReview,
    team: Team,
    user: User,
    user_access_control: UserAccessControl,
    new_since: datetime | None = None,
) -> list[PendingGroup]:
    """The review's queues as `user` sees them: the metrics queue drops metrics that read a table `user` cannot read."""
    others = [group for group in review.groups if group.kind != PendingKind.METRICS]
    metrics = _metrics_group(_visible_proposed_metrics(team, user, user_access_control), DEFAULT_SAMPLE_SIZE, new_since)
    return [metrics, *others] if metrics.count else others


def _visible_proposed_metrics(team: Team, user: User, user_access_control: UserAccessControl) -> QuerySet[Metric]:
    return metrics_visible_to_user(
        team,
        user,
        user_access_control,
        MetricListFilters(status=MetricStatus.PROPOSED),
        load_denied_tables=_denied_tables_for_proposed_metrics,
    )


@frozen
class PendingReviewBuild:
    reviews: dict[int, TeamPendingReview]
    failed_team_ids: list[int]


def build_org_pending_reviews(
    teams: list[Team], sample_size: int = DEFAULT_SAMPLE_SIZE, new_since: datetime | None = None
) -> PendingReviewBuild:
    """Teams with something to review, keyed by team id, and the teams that raised. Raises if all raised."""
    reviews: dict[int, TeamPendingReview] = {}
    failed_team_ids: list[int] = []
    for team in teams:
        try:
            review = build_team_pending_review(team, sample_size, new_since)
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
