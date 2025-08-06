import uuid
import json
import sys
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

    def test_temporal_async_logger_handles_none_exc_info(self):
        """Test that temporal async logger handles exc_info=(None, None, None) without crashing."""
        from posthog.temporal.common.logger import BASE_PROCESSORS, PRODUCTION_PROCESSORS

        # Configure structlog with the temporal processor constants
        processors = BASE_PROCESSORS + PRODUCTION_PROCESSORS

        structlog.configure(
            processors=processors,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )

        logger = structlog.get_logger("temporal_test")

        # This should work if BASE_PROCESSORS contains format_exc_info, fail if it doesn't
        # because PRODUCTION_PROCESSORS contains dict_tracebacks which needs format_exc_info
        logger.error("Test temporal logger", exc_info=sys.exc_info())
