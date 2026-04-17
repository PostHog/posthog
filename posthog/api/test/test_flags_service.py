"""
Tests for the feature flags service proxy functionality.

This module tests the secure detailed analysis feature and auth gating
for the Rust flags service integration.
"""

from unittest.mock import Mock, patch

from django.test import TestCase

from posthog.api.services.flags_service import get_flags_from_service


class TestFlagsService(TestCase):
    def setUp(self):
        self.test_token = "phc_test123"
        self.test_distinct_id = "user_123"
        self.mock_response_data = {
            "flags": {"test-flag": {"enabled": True}},
            "featureFlagPayloads": {},
        }

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_basic_flag_request(self, mock_session):
        """Test basic flag request without detailed analysis."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        response = get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id)

        # Verify the request was made correctly
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args

        # Check URL
        self.assertIn("/flags", call_args[0][0])

        # Check parameters
        params = call_args.kwargs["params"]
        self.assertEqual(params["v"], "2")
        self.assertNotIn("detailed_analysis", params)

        # Check payload
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["token"], self.test_token)
        self.assertEqual(payload["distinct_id"], self.test_distinct_id)

        # Check headers (should not have Authorization)
        headers = call_args.kwargs.get("headers", {})
        self.assertNotIn("Authorization", headers)

        # Check response
        self.assertEqual(response, self.mock_response_data)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_detailed_analysis_without_auth(self, mock_session):
        """Test detailed analysis request without authentication token."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, detailed_analysis=True)

        # Verify the request was made
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args

        # Check that detailed_analysis parameter is included
        params = call_args.kwargs["params"]
        self.assertEqual(params["detailed_analysis"], "true")

        # Check that no Authorization header is set
        headers = call_args.kwargs.get("headers", {})
        self.assertNotIn("Authorization", headers)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_detailed_analysis_with_auth(self, mock_session):
        """Test detailed analysis request with proper authentication."""
        mock_response = Mock()
        mock_response_with_conditions = {
            **self.mock_response_data,
            "conditions": [
                {
                    "index": 0,
                    "matched": True,
                    "explanation": "User matched condition",
                }
            ],
        }
        mock_response.json.return_value = mock_response_with_conditions
        mock_session.post.return_value = mock_response

        internal_token = "internal_auth_token_123"

        response = get_flags_from_service(
            token=self.test_token,
            distinct_id=self.test_distinct_id,
            detailed_analysis=True,
            internal_request_token=internal_token,
        )

        # Verify the request was made correctly
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args

        # Check parameters
        params = call_args.kwargs["params"]
        self.assertEqual(params["detailed_analysis"], "true")

        # Check Authorization header is set
        headers = call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {internal_token}")

        # Check response includes conditions
        self.assertIn("conditions", response)
        self.assertEqual(len(response["conditions"]), 1)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_empty_internal_token_ignored(self, mock_session):
        """Test that empty or whitespace-only internal tokens are ignored."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        # Test with empty string
        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, internal_request_token="")

        # Test with whitespace
        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, internal_request_token="   ")

        # Both calls should not include Authorization header
        for call in mock_session.post.call_args_list:
            headers = call.kwargs.get("headers", {})
            self.assertNotIn("Authorization", headers)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_person_properties_parameter(self, mock_session):
        """Test person_properties parameter is passed correctly."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        person_props = {"email": "test@example.com", "plan": "pro"}

        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, person_properties=person_props)

        # Check payload includes person_properties
        call_args = mock_session.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["person_properties"], person_props)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_only_use_override_person_properties(self, mock_session):
        """Test only_use_override_person_properties parameter."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        get_flags_from_service(
            token=self.test_token, distinct_id=self.test_distinct_id, only_use_override_person_properties=True
        )

        # Check parameter is set
        call_args = mock_session.post.call_args
        params = call_args.kwargs["params"]
        self.assertEqual(params["only_use_override_person_properties"], "true")

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_flag_keys_parameter(self, mock_session):
        """Test flag_keys parameter for filtering specific flags."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        flag_keys = ["flag1", "flag2", "flag3"]

        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, flag_keys=flag_keys)

        # Check payload includes flag_keys
        call_args = mock_session.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["flag_keys"], flag_keys)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_override_flags_definitions_parameter(self, mock_session):
        """Test override_flags_definitions parameter for historical evaluation."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        override_definitions = {
            "test-flag": {
                "key": "test-flag",
                "name": "Test Flag",
                "filters": {"groups": [{"rollout_percentage": 50}]},
                "active": True,
            }
        }

        get_flags_from_service(
            token=self.test_token, distinct_id=self.test_distinct_id, override_flags_definitions=override_definitions
        )

        # Check payload includes override_flags_definitions
        call_args = mock_session.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["override_flags_definitions"], override_definitions)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_groups_parameter(self, mock_session):
        """Test groups parameter for group-based flags."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        groups = {"company": "acme", "team": "engineering"}

        get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id, groups=groups)

        # Check payload includes groups
        call_args = mock_session.post.call_args
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["groups"], groups)

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_all_parameters_together(self, mock_session):
        """Test all parameters working together."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        get_flags_from_service(
            token=self.test_token,
            distinct_id=self.test_distinct_id,
            groups={"company": "test"},
            detailed_analysis=True,
            person_properties={"email": "test@example.com"},
            only_use_override_person_properties=True,
            flag_keys=["test-flag"],
            internal_request_token="auth_token",
            override_flags_definitions={"test-flag": {"key": "test-flag"}},
        )

        call_args = mock_session.post.call_args

        # Check all parameters are set
        params = call_args.kwargs["params"]
        self.assertEqual(params["v"], "2")
        self.assertEqual(params["detailed_analysis"], "true")
        self.assertEqual(params["only_use_override_person_properties"], "true")

        # Check all payload fields
        payload = call_args.kwargs["json"]
        self.assertEqual(payload["token"], self.test_token)
        self.assertEqual(payload["distinct_id"], self.test_distinct_id)
        self.assertEqual(payload["groups"], {"company": "test"})
        self.assertEqual(payload["person_properties"], {"email": "test@example.com"})
        self.assertEqual(payload["flag_keys"], ["test-flag"])
        self.assertEqual(payload["override_flags_definitions"], {"test-flag": {"key": "test-flag"}})

        # Check auth header
        headers = call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer auth_token")

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_http_error_handling(self, mock_session):
        """Test that HTTP errors are properly raised."""
        from requests import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("Service error", response=mock_response)
        mock_session.post.return_value = mock_response

        with self.assertRaises(HTTPError):
            get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id)

        # Verify raise_for_status was called
        mock_response.raise_for_status.assert_called_once()

    @patch("posthog.api.services.flags_service._FLAGS_SERVICE_SESSION")
    def test_configuration_settings(self, mock_session):
        """Test that configuration settings are used correctly."""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_response_data
        mock_session.post.return_value = mock_response

        with patch("posthog.api.services.flags_service.getattr") as mock_getattr:
            mock_getattr.side_effect = lambda settings, key, default: {
                "FEATURE_FLAGS_SERVICE_URL": "http://custom:8080",
                "FEATURE_FLAGS_SERVICE_PROXY_TIMEOUT": 5,
            }.get(key.split(".")[-1], default)

            get_flags_from_service(token=self.test_token, distinct_id=self.test_distinct_id)

            # Check that custom URL and timeout were used
            call_args = mock_session.post.call_args
            self.assertIn("http://custom:8080/flags", call_args[0][0])
            self.assertEqual(call_args.kwargs["timeout"], 5)
