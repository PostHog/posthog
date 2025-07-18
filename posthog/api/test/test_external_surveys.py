import json
import uuid
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

from django.test import TestCase
from django.core.cache import cache

from posthog.models import Survey
from posthog.test.base import APIBaseTest


class TestExternalSurveys(APIBaseTest):
    """
    Test suite for external survey functionality including the public_survey_page view.
    Focuses on security, performance, and proper survey rendering.
    """

    def setUp(self):
        super().setUp()
        cache.clear()

    def create_external_survey(self, **kwargs):
        """Helper method to create external surveys for testing"""
        # Generate unique name to avoid constraint violations
        unique_name = kwargs.get("name", f"Test External Survey {uuid.uuid4().hex[:8]}")
        default_data = {
            "team": self.team,
            "name": unique_name,
            "type": Survey.SurveyType.EXTERNAL_SURVEY,
            "questions": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "open",
                    "question": "What do you think of our product?",
                }
            ],
            "appearance": {
                "backgroundColor": "#1d4ed8",
                "submitButtonColor": "#2563eb",
            },
            "start_date": datetime.now(UTC) - timedelta(days=1),
            "end_date": None,
            "archived": False,
        }
        default_data.update(kwargs)
        return Survey.objects.create(**default_data)

    # SECURITY TESTS

    def test_valid_survey_id_required(self):
        """Test that invalid survey IDs are rejected"""
        # Invalid UUID format
        response = self.client.get(f"/external_surveys/invalid-id/")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Invalid request", status_code=400)

        # Valid UUID format but non-existent survey
        fake_uuid = str(uuid.uuid4())
        response = self.client.get(f"/external_surveys/{fake_uuid}/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Survey not available", status_code=404)

    def test_only_external_surveys_accessible(self):
        """Test that only external survey types can be accessed via public URL"""
        # Create non-external survey
        popover_survey = self.create_external_survey(type=Survey.SurveyType.POPOVER, name="Popover Survey")

        response = self.client.get(f"/external_surveys/{popover_survey.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Survey not receiving responses", status_code=404)

    def test_archived_surveys_not_accessible(self):
        """Test that archived surveys return 404"""
        survey = self.create_external_survey(archived=True)

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Survey not receiving responses", status_code=404)

    def test_survey_must_be_running(self):
        """Test survey availability based on start/end dates"""
        # Survey not started yet
        future_survey = self.create_external_survey(start_date=datetime.now(UTC) + timedelta(days=1))
        response = self.client.get(f"/external_surveys/{future_survey.id}/")
        self.assertEqual(response.status_code, 404)

        # Survey ended
        ended_survey = self.create_external_survey(
            start_date=datetime.now(UTC) - timedelta(days=2), end_date=datetime.now(UTC) - timedelta(days=1)
        )
        response = self.client.get(f"/external_surveys/{ended_survey.id}/")
        self.assertEqual(response.status_code, 404)

        # Survey never started
        never_started_survey = self.create_external_survey(start_date=None)
        response = self.client.get(f"/external_surveys/{never_started_survey.id}/")
        self.assertEqual(response.status_code, 404)

    def test_security_headers_present(self):
        """Test that proper security headers are set"""
        survey = self.create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        # Check security headers
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("Cache-Control", response)
        self.assertIn("Vary", response)

    def test_no_sensitive_data_exposed(self):
        """Test that sensitive survey data is not exposed in the template"""
        survey = self.create_external_survey(description="SENSITIVE: Internal team feedback for Q4 planning")

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        # Description should not be in the response
        self.assertNotContains(response, "SENSITIVE")
        self.assertNotContains(response, "Internal team feedback")

    # FUNCTIONALITY TESTS

    def test_successful_survey_rendering(self):
        """Test that a valid external survey renders correctly"""
        survey = self.create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        # Check that essential elements are present
        self.assertContains(response, survey.name)
        self.assertContains(response, str(survey.id))
        self.assertContains(response, "posthog-survey-container")

        # Check PostHog configuration is injected
        self.assertContains(response, "window.projectConfig")
        self.assertContains(response, survey.team.api_token)

    def test_survey_appearance_configuration(self):
        """Test that survey appearance settings are properly injected"""
        survey = self.create_external_survey(
            appearance={"backgroundColor": "#ff0000", "submitButtonColor": "#00ff00", "borderRadius": "12px"}
        )

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        # Check appearance data is injected
        self.assertContains(response, "window.surveyAppearance")
        self.assertContains(response, "#ff0000")
        self.assertContains(response, "#00ff00")

    def test_project_config_injection(self):
        """Test that project configuration is properly injected"""
        survey = self.create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        # Verify project config contains required fields
        content = response.content.decode()
        self.assertIn("window.projectConfig", content)
        self.assertIn(survey.team.api_token, content)

        # Extract and validate project config JSON
        import re

        config_match = re.search(r"window\.projectConfig = ({.*?});", content)
        self.assertIsNotNone(config_match)
        assert config_match is not None  # Type guard for mypy

        project_config = json.loads(config_match.group(1))
        self.assertIn("api_host", project_config)
        self.assertIn("token", project_config)

    # PERFORMANCE & CACHING TESTS

    def test_caching_headers(self):
        """Test that appropriate caching headers are set"""
        survey = self.create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

        cache_control = response.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertIn("max-age=300", cache_control)  # 5 minutes as per CACHE_TIMEOUT_SECONDS

    # ERROR HANDLING TESTS

    @patch("posthog.api.survey.logger")
    def test_database_error_handling(self, mock_logger):
        """Test proper error handling for database errors"""
        with patch("posthog.models.surveys.survey.Survey.objects.select_related") as mock_select:
            mock_select.side_effect = Exception("Database connection error")

            fake_uuid = str(uuid.uuid4())
            response = self.client.get(f"/external_surveys/{fake_uuid}/")

            self.assertEqual(response.status_code, 503)
            self.assertContains(response, "Service unavailable", status_code=503)
            mock_logger.exception.assert_called_once()

    @patch("posthog.api.survey.capture_exception")
    def test_exception_reporting(self, mock_capture):
        """Test that exceptions are properly reported to error tracking"""
        with patch("posthog.models.surveys.survey.Survey.objects.select_related") as mock_select:
            test_exception = Exception("Test error")
            mock_select.side_effect = test_exception

            fake_uuid = str(uuid.uuid4())
            self.client.get(f"/external_surveys/{fake_uuid}/")

            mock_capture.assert_called_once_with(test_exception)

    # INTEGRATION TESTS

    def test_cors_options_request(self):
        """Test that OPTIONS requests are handled for CORS"""
        survey = self.create_external_survey()

        response = self.client.options(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)

    def test_csrf_exemption(self):
        """Test that the view is properly exempt from CSRF protection"""
        survey = self.create_external_survey()

        # This should work without CSRF token
        response = self.client.get(f"/external_surveys/{survey.id}/")
        self.assertEqual(response.status_code, 200)


class TestExternalSurveysURLs(TestCase):
    """Test URL routing for external surveys"""

    def test_survey_url_pattern(self):
        """Test that survey URLs are properly routed"""
        from django.test import Client

        survey_id = str(uuid.uuid4())
        client = Client()

        # Test that the URL pattern matches correctly (should return 404 for non-existent survey)
        response = client.get(f"/external_surveys/{survey_id}/")
        # We expect 404 since survey doesn't exist, but URL should be routed correctly
        self.assertEqual(response.status_code, 404)
