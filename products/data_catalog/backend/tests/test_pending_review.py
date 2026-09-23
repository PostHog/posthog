from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.team import Team

from products.data_catalog.backend.facade.enums import CertificationStatus, MetricStatus, RelationshipStatus
from products.data_catalog.backend.logic.pending_review import (
    PendingKind,
    build_org_pending_reviews,
    build_team_pending_review,
)
from products.data_catalog.backend.models import Metric, RelationshipProposal, TableCertification
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


def _metric(team: Team, name: str, **kwargs) -> Metric:
    return Metric.objects.unscoped().create(team=team, name=name, description="d", **kwargs)


def _relationship(team: Team, fingerprint: str, **kwargs) -> RelationshipProposal:
    return RelationshipProposal.objects.unscoped().create(
        team=team,
        source_table_name="events",
        source_table_key="distinct_id",
        joining_table_name="persons",
        joining_table_key="id",
        field_name=f"linked_{fingerprint}",
        undirected_fingerprint=fingerprint,
        **kwargs,
    )


def _certification(team: Team, view_name: str, **kwargs) -> TableCertification:
    view = DataWarehouseSavedQuery.objects.create(team=team, name=view_name, query={"kind": "HogQLQuery"})
    return TableCertification.objects.unscoped().create(team=team, saved_query=view, **kwargs)


class TestBuildTeamPendingReview(BaseTest):
    def test_returns_none_when_nothing_is_pending(self) -> None:
        _metric(self.team, "approved_one", status=MetricStatus.APPROVED)
        _relationship(self.team, "fp_accepted", status=RelationshipStatus.ACCEPTED)
        _certification(self.team, "certified_view", status=CertificationStatus.CERTIFIED)

        assert build_team_pending_review(self.team) is None

    def test_counts_only_proposed_live_items_of_this_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        _metric(self.team, "proposed_one")
        _metric(self.team, "approved_one", status=MetricStatus.APPROVED)
        _metric(self.team, "deleted_one", deleted=True)
        _metric(other_team, "other_teams_metric")
        _relationship(self.team, "fp_proposed")
        _relationship(self.team, "fp_rejected", status=RelationshipStatus.REJECTED)
        _certification(self.team, "proposed_view")
        _certification(self.team, "deprecated_view", status=CertificationStatus.DEPRECATED)

        review = build_team_pending_review(self.team)

        assert review is not None
        assert review.team_id == self.team.id
        assert review.total == 3
        assert {group.kind: group.count for group in review.groups} == {
            PendingKind.METRICS: 1,
            PendingKind.RELATIONSHIPS: 1,
            PendingKind.CERTIFICATIONS: 1,
        }

    def test_groups_with_nothing_pending_are_left_out(self) -> None:
        _metric(self.team, "proposed_one")

        review = build_team_pending_review(self.team)

        assert review is not None
        assert [group.kind for group in review.groups] == [PendingKind.METRICS]

    def test_sample_names_are_the_oldest_items_first(self) -> None:
        for index in range(7):
            metric = _metric(self.team, f"metric_{index}")
            Metric.objects.unscoped().filter(pk=metric.pk).update(created_at=timezone.now() - timedelta(days=7 - index))

        review = build_team_pending_review(self.team, sample_size=3)

        assert review is not None
        group = review.groups[0]
        assert group.count == 7
        assert group.sample_names == ["metric_0", "metric_1", "metric_2"]

    def test_sample_names_describe_each_kind(self) -> None:
        _metric(self.team, "revenue", display_name="Monthly revenue")
        _relationship(self.team, "fp_proposed")
        _certification(self.team, "customer_facts")

        review = build_team_pending_review(self.team)

        assert review is not None
        samples = {group.kind: group.sample_names for group in review.groups}
        assert samples[PendingKind.METRICS] == ["Monthly revenue"]
        assert samples[PendingKind.RELATIONSHIPS] == ["events to persons"]
        assert samples[PendingKind.CERTIFICATIONS] == ["customer_facts"]


class TestBuildOrgPendingReviews(BaseTest):
    def test_keys_by_team_and_omits_teams_with_nothing_pending(self) -> None:
        quiet_team = Team.objects.create(organization=self.organization, name="Quiet")
        _metric(self.team, "proposed_one")

        reviews = build_org_pending_reviews([self.team, quiet_team])

        assert list(reviews) == [self.team.id]
        assert reviews[self.team.id].total == 1
