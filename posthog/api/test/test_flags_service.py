from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.api.services.flags_service import (
    FlagVersionConflictError,
    batch_evaluate_flag_for_team,
    get_flags_from_service,
)


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


class TestGetFlagsFromServiceRetries(SimpleTestCase):
    @patch("posthog.api.services.flags_service.time.sleep")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_retries_transient_connection_error_then_succeeds(self, mock_post, mock_sleep):
        ok = MagicMock()
        ok.json.return_value = {"flags": {}}
        mock_post.side_effect = [requests.exceptions.ConnectionError("refused"), ok]

        result = get_flags_from_service(token="phc_x", distinct_id="user-1", max_retries=2)

        self.assertEqual(result, {"flags": {}})
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("posthog.api.services.flags_service.time.sleep")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_raises_after_exhausting_retries(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        with self.assertRaises(requests.exceptions.ConnectionError):
            get_flags_from_service(token="phc_x", distinct_id="user-1", max_retries=2)

        self.assertEqual(mock_post.call_count, 3)

    @patch("posthog.api.services.flags_service.time.sleep")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_default_makes_no_retries(self, mock_post, mock_sleep):
        # The latency-sensitive live evaluation path must not gain retries by default.
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        with self.assertRaises(requests.exceptions.ConnectionError):
            get_flags_from_service(token="phc_x", distinct_id="user-1")

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("posthog.api.services.flags_service.time.sleep")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_negative_max_retries_raises_underlying_error_not_unreachable(self, mock_post, mock_sleep):
        # range(max_retries + 1) goes empty for a negative max_retries, which used to skip
        # the loop body entirely and fall through to the "unreachable" RuntimeError instead
        # of the connection error that actually happened.
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        with self.assertRaises(requests.exceptions.ConnectionError):
            get_flags_from_service(token="phc_x", distinct_id="user-1", max_retries=-1)

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("posthog.api.services.flags_service.time.sleep")
    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION.post")
    def test_does_not_retry_http_error_responses(self, mock_post, mock_sleep):
        # A 4xx/5xx is a real response, not a connection blip — retrying it just hammers the service.
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("500 Server Error", response=response)
        mock_post.return_value = response

        with self.assertRaises(requests.HTTPError):
            get_flags_from_service(token="phc_x", distinct_id="user-1", max_retries=2)

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()
