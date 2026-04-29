from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.resource_limits import check_count_limit, get_limit
from posthog.resource_limits.registry import REGISTRY, LimitDefinition


class TestGetLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.key = "analytics.max_dashboards_per_team"

    def test_returns_catalog_default(self) -> None:
        assert get_limit(team=self.team, key=self.key) == 500


class TestCheckCountLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.key = "analytics.max_dashboards_per_team"

    def test_below_threshold_emits_nothing(self) -> None:
        with patch("posthog.event_usage.report_user_action") as report:
            check_count_limit(team=self.team, key=self.key, current_count=10, user=self.user)
        report.assert_not_called()

    def test_one_below_threshold_emits_with_crossing_true(self) -> None:
        with patch("posthog.event_usage.report_user_action") as report:
            check_count_limit(team=self.team, key=self.key, current_count=499, user=self.user)
        report.assert_called_once()
        args, _ = report.call_args
        assert args[0] == self.user
        assert args[1] == "resource limit hit"
        properties = args[2]
        assert properties["limit_key"] == self.key
        assert properties["limit"] == 500
        assert properties["current_count"] == 499
        assert properties["crossing_threshold"] is True
        assert properties["team_id"] == self.team.id
        assert properties["organization_id"] == str(self.team.organization_id)

    def test_at_threshold_emits_with_crossing_false(self) -> None:
        with patch("posthog.event_usage.report_user_action") as report:
            check_count_limit(team=self.team, key=self.key, current_count=500, user=self.user)
        report.assert_called_once()
        properties = report.call_args[0][2]
        assert properties["crossing_threshold"] is False

    def test_far_above_threshold_still_emits(self) -> None:
        with patch("posthog.event_usage.report_user_action") as report:
            check_count_limit(team=self.team, key=self.key, current_count=10_000, user=self.user)
        report.assert_called_once()

    def test_no_user_no_emit(self) -> None:
        with patch("posthog.event_usage.report_user_action") as report:
            check_count_limit(team=self.team, key=self.key, current_count=499, user=None)
        report.assert_not_called()

    def test_never_raises(self) -> None:
        check_count_limit(team=self.team, key=self.key, current_count=10_000, user=self.user)


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
