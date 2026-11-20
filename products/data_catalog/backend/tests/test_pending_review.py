from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.db.models import QuerySet
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_catalog.backend.facade.enums import CertificationStatus, MetricStatus, RelationshipStatus
from products.data_catalog.backend.logic.metrics import metrics_for_team, metrics_visible_to_user
from products.data_catalog.backend.logic.pending_review import (
    PendingKind,
    build_org_pending_reviews,
    build_team_pending_review,
)
from products.data_catalog.backend.models import Metric, RelationshipProposal, TableCertification
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

_PENDING_REVIEW = "products.data_catalog.backend.logic.pending_review"


@contextmanager
def _failing_build_for(broken_team: Team) -> Iterator[None]:
    def metrics_for_team_failing_one_team(team: Team) -> QuerySet[Metric]:
        if team.id == broken_team.id:
            raise RuntimeError("catalog unavailable")
        return metrics_for_team(team)

    with patch(f"{_PENDING_REVIEW}.metrics_for_team", side_effect=metrics_for_team_failing_one_team):
        yield


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

        build = build_org_pending_reviews([self.team, quiet_team])

        assert list(build.reviews) == [self.team.id]
        assert build.reviews[self.team.id].total == 1
        assert build.failed_team_ids == []

    def test_reports_a_team_whose_build_raised_and_keeps_the_others(self) -> None:
        broken_team = Team.objects.create(organization=self.organization, name="Broken")
        _metric(self.team, "proposed_one")

        with _failing_build_for(broken_team):
            build = build_org_pending_reviews([self.team, broken_team])

        assert list(build.reviews) == [self.team.id]
        assert build.failed_team_ids == [broken_team.id]

    def test_raises_when_every_team_failed(self) -> None:
        with _failing_build_for(self.team), pytest.raises(RuntimeError):
            build_org_pending_reviews([self.team])


class TestPendingReviewAPI(APIBaseTest):
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_counts_proposed_items_the_caller_can_see(self, create_database: MagicMock) -> None:
        create_database.return_value = MagicMock(_denied_tables={"restricted_source"})
        _metric(self.team, "proposed_one")
        _metric(self.team, "approved_one", status=MetricStatus.APPROVED)
        _metric(self.team, "on_denied_table", referenced_table_names=["restricted_source"])
        _relationship(self.team, "fp_proposed")
        _relationship(self.team, "fp_rejected", status=RelationshipStatus.REJECTED)
        _certification(self.team, "proposed_view")
        _certification(self.team, "certified_view", status=CertificationStatus.CERTIFIED)

        responses = [self.client.get(f"/api/projects/{self.team.id}/data_catalog/pending_review/") for _ in range(2)]

        assert [response.json() for response in responses] == [
            {"metrics": 1, "relationships": 1, "certifications": 1}
        ] * 2
        create_database.assert_called_once()

    @parameterized.expand(
        [
            ("a_new_proposal_gets_a_fresh_table_check", "add", 1),
            ("a_reviewed_proposal_keeps_the_cached_table_check", "review", 2),
        ]
    )
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_count_after_table_access_is_revoked(
        self, _name: str, change: str, expected_count: int, create_database: MagicMock
    ) -> None:
        create_database.return_value = MagicMock(_denied_tables=set())
        _metric(self.team, "reads_no_table")
        _metric(self.team, "on_source", referenced_table_names=["restricted_source"])
        reviewed_later = _metric(self.team, "also_on_source", referenced_table_names=["restricted_source"])
        url = f"/api/projects/{self.team.id}/data_catalog/pending_review/"
        count_before = self.client.get(url).json()["metrics"]

        create_database.return_value = MagicMock(_denied_tables={"restricted_source"})
        if change == "add":
            _metric(self.team, "new_on_source", referenced_table_names=["restricted_source"])
        else:
            Metric.objects.unscoped().filter(id=reviewed_later.id).update(status=MetricStatus.APPROVED)

        assert (count_before, self.client.get(url).json()["metrics"]) == (3, expected_count)

    @patch("posthog.utils.cache")
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_counts_metrics_when_the_cache_is_unavailable(self, create_database: MagicMock, cache: MagicMock) -> None:
        create_database.return_value = MagicMock(_denied_tables={"restricted_source"})
        cache.get.side_effect = ConnectionError
        cache.set.side_effect = ConnectionError
        _metric(self.team, "proposed_one")
        _metric(self.team, "on_denied_table", referenced_table_names=["restricted_source"])

        response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/pending_review/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["metrics"] == 1

    @patch("products.data_catalog.backend.logic.metrics.system_table_denials", return_value=frozenset())
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_count_follows_a_change_of_membership_level(
        self, create_database: MagicMock, _system_table_denials: MagicMock
    ) -> None:
        create_database.return_value = MagicMock(_denied_tables={"restricted_source"})
        _metric(self.team, "on_denied_table", referenced_table_names=["restricted_source"])
        url = f"/api/projects/{self.team.id}/data_catalog/pending_review/"

        counts = []
        for level in (OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.MEMBER):
            self.organization_membership.level = level
            self.organization_membership.save()
            counts.append(self.client.get(url).json()["metrics"])

        assert counts == [1, 0]

    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_metric_added_after_the_table_check_stays_hidden(self, create_database: MagicMock) -> None:
        create_database.return_value = MagicMock(_denied_tables={"restricted_source"})
        _metric(self.team, "reads_no_table")
        visible = metrics_visible_to_user(self.team, self.user, UserAccessControl(user=self.user, team=self.team))

        _metric(self.team, "on_denied_table", referenced_table_names=["restricted_source"])

        assert [metric.name for metric in visible] == ["reads_no_table"]

    @parameterized.expand(
        [
            ("member_with_nothing_proposed", OrganizationMembership.Level.MEMBER, [], 0),
            ("member_with_proposals_that_read_no_table", OrganizationMembership.Level.MEMBER, [[], []], 2),
            ("admin", OrganizationMembership.Level.ADMIN, [["safe_source"], ["system.restricted"]], 1),
        ]
    )
    @patch("products.data_catalog.backend.logic.metrics.system_table_denials", return_value=frozenset({"restricted"}))
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_counts_metrics_without_building_the_hogql_database(
        self,
        _name: str,
        level: OrganizationMembership.Level,
        proposed_references: list[list[str]],
        expected_metrics: int,
        create_database: MagicMock,
        _system_table_denials: MagicMock,
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        for index, references in enumerate(proposed_references):
            _metric(self.team, f"proposed_{index}", referenced_table_names=references)

        response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/pending_review/")

        assert response.json()["metrics"] == expected_metrics
        create_database.assert_not_called()

    @parameterized.expand(
        [
            (f"{path}_{name}", path, scopes, expected_status)
            for path in ("pending_review", "metric_availability")
            for name, scopes, expected_status in (
                ("catalog_read_scope", ["data_catalog:read"], status.HTTP_200_OK),
                ("unrelated_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
            )
        ]
    )
    def test_personal_api_key_needs_the_catalog_read_scope(
        self, _name: str, path: str, scopes: list[str], expected_status: int
    ) -> None:
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(raw_key), scopes=scopes)

        response = self.client.get(
            f"/api/projects/{self.team.id}/data_catalog/{path}/", HTTP_AUTHORIZATION=f"Bearer {raw_key}"
        )

        assert response.status_code == expected_status, response.json()


class TestMetricAvailabilityAPI(APIBaseTest):
    @parameterized.expand(
        [
            ("no_metrics", [], False),
            ("only_deleted_metrics", [{"deleted": True}], False),
            ("metric_on_a_denied_table", [{"referenced_table_names": ["restricted_source"]}], True),
        ]
    )
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_reports_live_metrics_without_building_the_hogql_database(
        self, _name: str, metrics: list[dict], expected: bool, create_database: MagicMock
    ) -> None:
        for index, fields in enumerate(metrics):
            _metric(self.team, f"metric_{index}", **fields)

        response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metric_availability/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"has_metrics": expected}
        create_database.assert_not_called()
