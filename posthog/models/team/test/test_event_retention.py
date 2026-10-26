from datetime import timedelta
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization, ProductFeature
from posthog.models.organization_events_retention_setting import OrganizationEventsRetentionSetting
from posthog.models.team import event_retention
from posthog.models.team.event_retention import (
    choose_organization_events_retention,
    parse_events_feature_to_months,
    reconcile_organization_events_retention,
)
from posthog.models.team.team import Team


class TestParseEventsFeatureToMonths:
    @parameterized.expand(
        [
            (None, 84),
            ({"limit": 1, "unit": "year"}, 12),
            ({"limit": 2, "unit": "years"}, 24),
            ({"limit": 5, "unit": "years"}, 60),
            ({"limit": 7, "unit": "years"}, 84),
            ({"limit": 10, "unit": "years"}, 120),
            ({"limit": 6, "unit": "months"}, 6),
            ({"limit": 18, "unit": "months"}, 18),
            ({"limit": 84, "unit": "months"}, 84),
            ({"limit": None, "unit": "years"}, 84),
            ({"limit": 1, "unit": "decades"}, 84),
            ({"limit": 90, "unit": "days"}, 84),
            ({"limit": 0, "unit": "years"}, 84),
            ({"limit": 0, "unit": "months"}, 84),
            ({"limit": -5, "unit": "years"}, 84),
        ]
    )
    def test_parse(self, feature: dict | None, expected: int) -> None:
        assert parse_events_feature_to_months(cast(ProductFeature | None, feature)) == expected


class TestReconcileOrganizationEventsRetention(BaseTest):
    def _set_retention_feature(self, limit: int, unit: str) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[{"key": "product_analytics_data_retention", "limit": limit, "unit": unit}]
        )
        self.organization.refresh_from_db()

    def test_updates_all_mismatched_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        previous_updated_at = timezone.now() - timedelta(days=1)
        Team.objects.filter(pk__in=[self.team.pk, other_team.pk]).update(
            event_retention_months=84, updated_at=previous_updated_at
        )
        self._set_retention_feature(1, "year")

        assert reconcile_organization_events_retention(self.organization) == 2

        self.team.refresh_from_db()
        other_team.refresh_from_db()
        assert self.team.event_retention_months == 12
        assert other_team.event_retention_months == 12
        assert self.team.updated_at > previous_updated_at
        assert other_team.updated_at > previous_updated_at

    def test_no_write_when_already_aligned(self) -> None:
        self._set_retention_feature(7, "years")
        Team.objects.filter(pk=self.team.pk).update(event_retention_months=84)

        assert reconcile_organization_events_retention(self.organization) == 0

    def test_reconciles_from_persisted_entitlement_not_snapshot(self) -> None:
        Team.objects.filter(pk=self.team.pk).update(event_retention_months=84)
        stale_org = Organization.objects.get(pk=self.organization.pk)
        self._set_retention_feature(1, "year")

        assert reconcile_organization_events_retention(stale_org) == 1

        self.team.refresh_from_db()
        assert self.team.event_retention_months == 12

    def test_plan_caps_the_chosen_window_and_an_upgrade_restores_it(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._set_retention_feature(5, "years")
        assert choose_organization_events_retention(self.organization, 24) == 24

        for features, expected_months in [((1, "year"), 12), ((7, "years"), 24)]:
            self._set_retention_feature(*features)
            reconcile_organization_events_retention(self.organization)
            self.team.refresh_from_db()
            other_team.refresh_from_db()
            assert self.team.event_retention_months == expected_months
            assert other_team.event_retention_months == expected_months

    def test_window_chosen_during_reconcile_is_kept(self) -> None:
        Team.objects.filter(pk=self.team.pk).update(event_retention_months=84)
        self._set_retention_feature(2, "years")
        target_months = event_retention.events_retention_target_months

        def choose_after_teams_are_read(organization_months: int, chosen_months: int | None) -> int:
            OrganizationEventsRetentionSetting.objects.create(organization=self.organization, retention_months=12)
            Team.objects.filter(pk=self.team.pk).update(event_retention_months=12)
            return target_months(organization_months, chosen_months)

        with patch.object(event_retention, "events_retention_target_months", side_effect=choose_after_teams_are_read):
            assert reconcile_organization_events_retention(self.organization) == 0

        self.team.refresh_from_db()
        assert self.team.event_retention_months == 12
