from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.customer_analytics.backend.logic.account_property_fanout_flags import (
    ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG,
    ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_FLAG,
    account_property_sync_fanout_enabled,
    get_account_property_sync_source_concurrency,
)

_MODULE = "products.customer_analytics.backend.logic.account_property_fanout_flags"
_FEATURE_ENABLED = f"{_MODULE}.posthoganalytics.feature_enabled"
_FEATURE_FLAG_PAYLOAD = f"{_MODULE}.posthoganalytics.get_feature_flag_payload"


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
            patch(f"{_MODULE}.capture_exception"),
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


class AccountPropertySyncSourceConcurrencyFlagTest(BaseTest):
    @parameterized.expand(
        [
            ("payload_value", {"source_concurrency": 8}, 8),
            ("json_string_payload", '{"source_concurrency": 5}', 5),
            ("above_maximum", {"source_concurrency": 500}, 20),
            ("missing_flag", None, 3),
            ("missing_key", {}, 3),
            ("zero", {"source_concurrency": 0}, 3),
            ("float", {"source_concurrency": 4.5}, 3),
            ("boolean", {"source_concurrency": True}, 3),
            ("malformed_json", "{not json", 3),
            ("flag_service_error", RuntimeError("flag service unavailable"), 3),
        ]
    )
    def test_targets_the_team_organization_and_falls_back_to_the_default(
        self, _name: str, payload: object, expected: int
    ) -> None:
        organization_id = str(self.team.organization_id)

        with (
            patch(_FEATURE_FLAG_PAYLOAD, side_effect=[payload]) as feature_flag_payload,
            patch(f"{_MODULE}.capture_exception"),
        ):
            assert get_account_property_sync_source_concurrency(self.team.id) == expected

        feature_flag_payload.assert_called_once_with(
            ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
