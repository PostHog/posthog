from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.resource_limits import LimitKey, check_count_limit, get_limit, get_organization_limit
from posthog.resource_limits.registry import REGISTRY, LimitDefinition


class TestGetLimit(BaseTest):
    def test_returns_catalog_default(self) -> None:
        assert get_limit(team=self.team, key=LimitKey.MAX_DASHBOARDS_PER_TEAM) == 500


class TestCheckCountLimit(BaseTest):
    @parameterized.expand(
        [
            ("below_threshold", 10, False, None),
            ("one_below_threshold", 499, True, True),
            ("at_threshold", 500, True, False),
            ("far_above_threshold", 10_000, True, False),
        ]
    )
    def test_emit_at_boundary(
        self,
        _name: str,
        current_count: int,
        expect_emit: bool,
        expect_crossing: bool | None,
    ) -> None:
        with patch("posthog.resource_limits.evaluator.report_user_action") as report:
            check_count_limit(
                team=self.team,
                key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
                current_count=current_count,
                user=self.user,
            )
        if not expect_emit:
            report.assert_not_called()
            return
        report.assert_called_once()
        args, _ = report.call_args
        assert args[0] == self.user
        assert args[1] == "resource limit hit"
        properties = args[2]
        assert properties["limit_key"] == LimitKey.MAX_DASHBOARDS_PER_TEAM
        assert properties["limit"] == 500
        assert properties["current_count"] == current_count
        assert properties["crossing_threshold"] is expect_crossing
        assert properties["team_id"] == self.team.id
        assert properties["organization_id"] == str(self.team.organization_id)

    def test_no_user_no_emit(self) -> None:
        with patch("posthog.resource_limits.evaluator.report_user_action") as report:
            check_count_limit(
                team=self.team,
                key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
                current_count=499,
                user=None,
            )
        report.assert_not_called()


class TestGetOrganizationLimit(BaseTest):
    @parameterized.expand(
        [
            ("free_no_features", [], 20),
            ("paid_with_subscriptions", [{"key": AvailableFeature.SUBSCRIPTIONS}], 40),
            ("enterprise_with_saml", [{"key": AvailableFeature.SAML}], 200),
        ]
    )
    def test_resolves_tiered_limit(
        self,
        _name: str,
        available_product_features: list,
        expected_limit: int,
    ) -> None:
        self.organization.available_product_features = available_product_features
        self.organization.save()
        assert (
            get_organization_limit(
                organization=self.organization,
                key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
            )
            == expected_limit
        )

    def test_falls_back_to_default_when_no_tier_overrides(self) -> None:
        # MAX_DASHBOARDS_PER_TEAM has no by_plan_tier, so any org sees the catalog default.
        self.organization.available_product_features = [{"key": AvailableFeature.SAML}]
        self.organization.save()
        assert (
            get_organization_limit(
                organization=self.organization,
                key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
            )
            == 500
        )


class TestRegistryShape:
    def test_every_entry_key_matches_its_dict_key(self) -> None:
        for dict_key, defn in REGISTRY.items():
            assert defn.key == dict_key, f"Registry key {dict_key} does not match LimitDefinition.key={defn.key}"

    def test_every_entry_has_non_empty_description(self) -> None:
        for defn in REGISTRY.values():
            assert defn.description.strip(), f"Limit {defn.key} has an empty description"

    def test_entries_are_limit_definition_instances(self) -> None:
        for defn in REGISTRY.values():
            assert isinstance(defn, LimitDefinition)
