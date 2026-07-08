from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.api.services.flags_service import FlagVersionConflictError, batch_evaluate_flag_for_team


class TestBatchEvaluateFlagForTeam(SimpleTestCase):
    @parameterized.expand([("unset", None), ("empty", ""), ("whitespace", "   ")])
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_missing_internal_request_token_fails_fast(self, _name, token, mock_post):
        with override_settings(INTERNAL_REQUEST_TOKEN=token):
            with self.assertRaises(ImproperlyConfigured):
                batch_evaluate_flag_for_team(
                    team_id=1,
                    project_id=1,
                    flag_key="my-flag",
                    expected_version=0,
                    cursor=0,
                    limit=100,
                )
        mock_post.assert_not_called()

    @override_settings(INTERNAL_REQUEST_TOKEN="secret")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_409_maps_to_flag_version_conflict_before_raise_for_status(self, mock_post):
        response = MagicMock()
        response.status_code = 409
        mock_post.return_value = response

        with self.assertRaises(FlagVersionConflictError):
            batch_evaluate_flag_for_team(
                team_id=1,
                project_id=1,
                flag_key="my-flag",
                expected_version=7,
                cursor=0,
                limit=100,
            )
        # The 409 branch must short-circuit: a generic HTTPError from raise_for_status
        # would lose the version-conflict semantics the paging loop relies on.
        response.raise_for_status.assert_not_called()
        response.json.assert_not_called()

    @override_settings(INTERNAL_REQUEST_TOKEN="secret")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_5xx_still_raises_for_status(self, mock_post):
        response = MagicMock()
        response.status_code = 503
        response.raise_for_status.side_effect = requests.HTTPError("503 Server Error", response=response)
        mock_post.return_value = response

        with self.assertRaises(requests.HTTPError):
            batch_evaluate_flag_for_team(
                team_id=1,
                project_id=1,
                flag_key="my-flag",
                expected_version=0,
                cursor=0,
                limit=100,
            )
