import uuid
import json
from unittest.mock import patch
from django.test import TestCase
from io import StringIO
import structlog

from posthog.exceptions_capture import capture_exception


class TestExceptionsCapture(TestCase):
    def _setup_structlog_capture(self):
        """Configure structlog to capture output and return the StringIO buffer"""
        output = StringIO()
        structlog.configure(
            processors=[structlog.processors.format_exc_info, structlog.processors.JSONRenderer()],
            logger_factory=lambda *args: structlog.WriteLogger(output),
            cache_logger_on_first_use=False,
        )
        return output

    @patch("posthoganalytics.api_key", "test-key")
    @patch("posthoganalytics.capture_exception")
    def test_capture_exception_with_none_exc_info(self, mock_posthog_capture):
        """Test that structlog handles exc_info=(None, None, None) gracefully"""
        mock_posthog_capture.return_value = str(uuid.uuid4())
        output = self._setup_structlog_capture()

        test_exception = ValueError("Test error without context")
        capture_exception(test_exception)

        log_data = json.loads(output.getvalue().strip())
        self.assertIn("Exception captured: Test error without context", log_data["event"])
        self.assertEqual(log_data["exception"], "MISSING")

    @patch("posthoganalytics.api_key", "test-key")
    @patch("posthoganalytics.capture_exception")
    def test_capture_exception_with_real_exc_info(self, mock_posthog_capture):
        """Test that structlog properly formats real exception info"""
        mock_posthog_capture.return_value = str(uuid.uuid4())
        output = self._setup_structlog_capture()

        try:
            raise ValueError("Test error with context")
        except ValueError as e:
            capture_exception(e)

        log_data = json.loads(output.getvalue().strip())
        self.assertIn("Exception captured: Test error with context", log_data["event"])
        self.assertIn("ValueError: Test error with context", log_data["exception"])
        self.assertIn("Traceback", log_data["exception"])
