from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from posthog.models.events_retention_config import (
    OrganizationEventsRetentionConfig,
    TeamEventsRetentionConfig,
    effective_events_retention,
)
from posthog.models.organization import Organization
from posthog.models.team import Team


class TestEventsRetentionConfig(BaseTest):
    @parameterized.expand(
        [
            ("inside_range", 12, 24, 18, True),
            ("on_lower_bound", 12, 24, 12, True),
            ("below_range", 12, 24, 6, False),
            ("above_range", 12, 24, 36, False),
            ("no_org_range", None, None, 1, True),
            ("only_min", 12, None, 120, True),
        ]
    )
    def test_team_value_has_to_fall_in_org_range(
        self, _name: str, low: int | None, high: int | None, months: int, valid: bool
    ) -> None:
        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, min_events_retention_months=low, max_events_retention_months=high
        )
        config = TeamEventsRetentionConfig(team=self.team, events_retention_months=months)

        if valid:
            config.full_clean()
        else:
            with self.assertRaises(ValidationError) as error:
                config.full_clean()
            assert "events_retention_months" in error.exception.message_dict

    @parameterized.expand(
        [
            ("excludes_team_below", 13, 24, False),
            ("excludes_team_above", 6, 12, False),
            ("includes_team", 12, 24, True),
        ]
    )
    def test_org_range_has_to_cover_existing_team_values(self, _name: str, low: int, high: int, valid: bool) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        TeamEventsRetentionConfig.objects.create(team=self.team, events_retention_months=12)
        TeamEventsRetentionConfig.objects.create(team=other_team, events_retention_months=24)
        config = OrganizationEventsRetentionConfig(
            organization=self.organization, min_events_retention_months=low, max_events_retention_months=high
        )

        if valid:
            config.full_clean()
        else:
            with self.assertRaises(ValidationError) as error:
                config.full_clean()
            assert "Change those teams first" in str(error.exception)

    def test_org_default_has_to_fall_in_org_range(self) -> None:
        config = OrganizationEventsRetentionConfig(
            organization=self.organization,
            default_events_retention_months=6,
            min_events_retention_months=12,
            max_events_retention_months=24,
        )

        with self.assertRaises(ValidationError) as error:
            config.full_clean()
        assert "default_events_retention_months" in error.exception.message_dict

    def test_effective_retention_prefers_the_team_value_over_the_org_default(self) -> None:
        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=13
        )
        overrides = Team.objects.create(organization=self.organization, name="Overrides")
        TeamEventsRetentionConfig.objects.create(team=overrides, events_retention_months=18)
        cleared = Team.objects.create(organization=self.organization, name="Cleared")
        TeamEventsRetentionConfig.objects.create(team=cleared, events_retention_months=None)
        other_org = Organization.objects.create(name="No default")
        Team.objects.create(organization=other_org, name="Keeps everything")
        own_value = Team.objects.create(organization=other_org, name="Own value")
        TeamEventsRetentionConfig.objects.create(team=own_value, events_retention_months=24)

        retention = {(item.organization_id, item.team_id): item.months for item in effective_events_retention()}

        assert retention == {
            (self.organization.id, self.team.id): 13,
            (self.organization.id, overrides.id): 18,
            (self.organization.id, cleared.id): 13,
            (other_org.id, own_value.id): 24,
        }
