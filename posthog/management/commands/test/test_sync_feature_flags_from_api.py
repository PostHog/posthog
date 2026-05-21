from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.management.commands.sync_feature_flags_from_api import sync_feature_flags_from_api
from posthog.models import FeatureFlag


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


class TestSyncFeatureFlagsFromApi(BaseTest):
    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_skipped_when_no_personal_api_key(self, mock_get):
        outputs: list[str] = []

        with patch.dict("os.environ", {}, clear=True):
            sync_feature_flags_from_api(output_fn=outputs.append)

        mock_get.assert_not_called()
        assert any("Skipping feature flag sync" in line for line in outputs)
        assert not FeatureFlag.objects.exists()

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_creates_multivariate_flag_with_full_filters(self, mock_get):
        multivariate_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
            "payloads": {},
        }
        mock_get.return_value = _mock_response(
            {
                "results": [
                    {
                        "key": "multivariate-flag",
                        "name": "My multivariate flag",
                        "active": True,
                        "filters": multivariate_filters,
                    },
                ],
                "next": None,
            }
        )

        sync_feature_flags_from_api(personal_api_key="phx_test", output_fn=lambda _: None)

        flag = FeatureFlag.objects.get(team=self.team, key="multivariate-flag")
        assert flag.active is True
        assert flag.filters == multivariate_filters
        assert flag.filters.get("multivariate", {}).get("variants")

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_creates_boolean_flag_with_full_filters(self, mock_get):
        boolean_filters = {
            "groups": [{"properties": [], "rollout_percentage": 75}],
            "payloads": {},
        }
        mock_get.return_value = _mock_response(
            {
                "results": [
                    {
                        "key": "boolean-flag",
                        "name": "My boolean flag",
                        "active": True,
                        "filters": boolean_filters,
                    },
                ],
                "next": None,
            }
        )

        sync_feature_flags_from_api(personal_api_key="phx_test", output_fn=lambda _: None)

        flag = FeatureFlag.objects.get(team=self.team, key="boolean-flag")
        assert flag.filters == boolean_filters

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_falls_back_to_default_filters_when_missing(self, mock_get):
        mock_get.return_value = _mock_response(
            {
                "results": [
                    {"key": "filterless-flag", "active": True},
                ],
                "next": None,
            }
        )

        sync_feature_flags_from_api(personal_api_key="phx_test", output_fn=lambda _: None)

        flag = FeatureFlag.objects.get(team=self.team, key="filterless-flag")
        assert flag.filters == {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {},
        }

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_deactivates_flag_when_active_field_is_false(self, mock_get):
        FeatureFlag.objects.create(
            team=self.team,
            key="going-inactive",
            name="going-inactive",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}},
        )
        mock_get.return_value = _mock_response(
            {
                "results": [
                    {
                        "key": "going-inactive",
                        "active": False,
                        "filters": {"groups": [], "payloads": {}},
                    },
                ],
                "next": None,
            }
        )

        sync_feature_flags_from_api(personal_api_key="phx_test", output_fn=lambda _: None)

        flag = FeatureFlag.objects.get(team=self.team, key="going-inactive")
        assert flag.active is False

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_authorization_header_is_sent(self, mock_get):
        mock_get.return_value = _mock_response({"results": [], "next": None})

        sync_feature_flags_from_api(personal_api_key="phx_secret", output_fn=lambda _: None)

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer phx_secret"

    @patch("posthog.management.commands.sync_feature_flags_from_api.requests.get")
    def test_follows_pagination(self, mock_get):
        mock_get.side_effect = [
            _mock_response(
                {
                    "results": [{"key": "flag-1", "active": True, "filters": None}],
                    "next": "https://us.posthog.com/api/projects/2/feature_flags/?limit=200&offset=200",
                }
            ),
            _mock_response(
                {
                    "results": [{"key": "flag-2", "active": True, "filters": None}],
                    "next": None,
                }
            ),
        ]

        sync_feature_flags_from_api(personal_api_key="phx_test", output_fn=lambda _: None)

        assert mock_get.call_count == 2
        assert FeatureFlag.objects.filter(team=self.team, key="flag-1").exists()
        assert FeatureFlag.objects.filter(team=self.team, key="flag-2").exists()
