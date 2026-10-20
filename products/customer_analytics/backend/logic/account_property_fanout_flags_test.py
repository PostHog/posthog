from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.customer_analytics.backend.logic.account_property_fanout_flags import (
    ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG,
    account_property_sync_fanout_enabled,
)

_FEATURE_ENABLED = (
    "products.customer_analytics.backend.logic.account_property_fanout_flags.posthoganalytics.feature_enabled"
)


class AccountPropertySyncFanoutFlagTest(BaseTest):
    @parameterized.expand(
        [
            ("enabled", True, True),
            ("disabled", False, False),
            ("missing_flag", None, False),
            ("flag_service_error", RuntimeError("flag service unavailable"), False),
        ]
    )
    def test_targets_the_team_organization_and_fails_closed(
        self, _name: str, flag_result: object, expected: bool
    ) -> None:
        organization_id = str(self.team.organization_id)

        with (
            patch(_FEATURE_ENABLED, side_effect=[flag_result]) as feature_enabled,
            patch("products.customer_analytics.backend.logic.account_property_fanout_flags.capture_exception"),
        ):
            assert account_property_sync_fanout_enabled(self.team.id) is expected

        feature_enabled.assert_called_once_with(
            ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_unknown_team_selects_legacy_without_calling_the_flag_service(self) -> None:
        with patch(_FEATURE_ENABLED) as feature_enabled:
            assert account_property_sync_fanout_enabled(self.team.id + 10_000) is False

        feature_enabled.assert_not_called()
