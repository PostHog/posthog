import json

from posthog.test.base import BaseTest

from posthog.models import ScheduledChange


class TestScheduledChange(BaseTest):
    def setUp(self):
        super().setUp()
        self.scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id="test-flag",
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": True},
            scheduled_at="2025-07-22 12:00:00+00:00",
            created_by=self.user,
        )

    def test_formatted_failure_reason_with_null(self):
        """Test that null failure_reason returns 'Unknown error'"""
        self.scheduled_change.failure_reason = None
        self.assertEqual(self.scheduled_change.formatted_failure_reason, "Unknown error")

    def test_formatted_failure_reason_with_empty_string(self):
        """Test that empty failure_reason returns 'Unknown error'"""
        self.scheduled_change.failure_reason = ""
        self.assertEqual(self.scheduled_change.formatted_failure_reason, "Unknown error")

    def test_formatted_failure_reason_legacy_string(self):
        """Test that legacy string failure reasons are returned as-is"""
        self.scheduled_change.failure_reason = "Database connection failed"
        self.assertEqual(self.scheduled_change.formatted_failure_reason, "Database connection failed")

    def test_formatted_failure_reason_json_unrecoverable(self):
        """Test JSON format for unrecoverable errors"""
        failure_context = {
            "error": "Invalid payload structure",
            "error_type": "ValidationError",
            "error_classification": "unrecoverable",
            "will_retry": False,
            "retry_count": 1,
            "max_retries": 5,
            "timestamp": "2025-07-22T22:47:00Z",
            "hostname": "worker-1",  # Sensitive info that should not be exposed
            "task_id": "abc123",  # Sensitive info that should not be exposed
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        expected = "Invalid payload structure (permanent error)"
        self.assertEqual(self.scheduled_change.formatted_failure_reason, expected)

    def test_formatted_failure_reason_json_retry_exhausted(self):
        """Test JSON format for retry exhausted"""
        failure_context = {
            "error": "Database connection lost",
            "error_type": "OperationalError",
            "error_classification": "recoverable",
            "will_retry": False,
            "retry_exhausted": True,
            "retry_count": 5,
            "max_retries": 5,
            "timestamp": "2025-07-22T22:47:00Z",
            "hostname": "worker-2",  # Sensitive info that should not be exposed
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        expected = "Database connection lost (failed after 5 out of 5 attempts)"
        self.assertEqual(self.scheduled_change.formatted_failure_reason, expected)

    def test_formatted_failure_reason_json_will_retry(self):
        """Test JSON format for retryable errors"""
        failure_context = {
            "error": "Temporary service unavailable",
            "error_type": "OperationalError",
            "error_classification": "recoverable",
            "will_retry": True,
            "retry_count": 2,
            "max_retries": 5,
            "timestamp": "2025-07-22T22:47:00Z",
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        expected = "Temporary service unavailable (will retry automatically, 3 attempts remaining)"
        self.assertEqual(self.scheduled_change.formatted_failure_reason, expected)

    def test_formatted_failure_reason_json_will_retry_one_attempt(self):
        """Test JSON format for retryable errors with only one attempt remaining"""
        failure_context = {
            "error": "API rate limit exceeded",
            "error_type": "RateLimitError",
            "error_classification": "recoverable",
            "will_retry": True,
            "retry_count": 4,
            "max_retries": 5,
            "timestamp": "2025-07-22T22:47:00Z",
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        expected = "API rate limit exceeded (will retry automatically, 1 attempt remaining)"
        self.assertEqual(self.scheduled_change.formatted_failure_reason, expected)

    def test_formatted_failure_reason_json_no_error_field(self):
        """Test JSON without error field falls back to string representation"""
        invalid_context = {
            "message": "Some other format",
            "timestamp": "2025-07-22T22:47:00Z",
        }
        self.scheduled_change.failure_reason = json.dumps(invalid_context)

        # Should return the JSON string as-is since no 'error' field
        self.assertEqual(self.scheduled_change.formatted_failure_reason, json.dumps(invalid_context))

    def test_formatted_failure_reason_malformed_json(self):
        """Test malformed JSON falls back to string representation"""
        malformed_json = '{"error": "test", invalid json'
        self.scheduled_change.failure_reason = malformed_json

        # Should return the malformed JSON as-is
        self.assertEqual(self.scheduled_change.formatted_failure_reason, malformed_json)

    def test_formatted_failure_reason_basic_error_only(self):
        """Test JSON with just error field and no retry status"""
        failure_context = {
            "error": "Some generic error",
            "error_type": "Exception",
            "timestamp": "2025-07-22T22:47:00Z",
            # Missing retry status fields
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        # Should just return the error message without any retry status
        self.assertEqual(self.scheduled_change.formatted_failure_reason, "Some generic error")

    def test_sensitive_data_not_exposed(self):
        """Test that sensitive data from failure context is not exposed"""
        failure_context = {
            "error": "Database connection failed",
            "error_type": "OperationalError",
            "hostname": "internal-worker-node-123",
            "task_id": "celery-task-abc-def-123",
            "worker_hostname": "worker.internal.company.com",
            "api_key": "sk-1234567890abcdef",  # This should never be exposed
            "database_url": "postgresql://user:pass@internal:5432/db",  # This should never be exposed
            "will_retry": False,
            "error_classification": "recoverable",
            "retry_exhausted": True,
            "retry_count": 3,
        }
        self.scheduled_change.failure_reason = json.dumps(failure_context)

        formatted = self.scheduled_change.formatted_failure_reason

        # Should only contain the error message and retry info
        self.assertEqual(formatted, "Database connection failed (failed after 3 attempts)")

        # Should not contain any sensitive information
        self.assertNotIn("internal-worker-node-123", formatted)
        self.assertNotIn("celery-task-abc-def-123", formatted)
        self.assertNotIn("worker.internal.company.com", formatted)
        self.assertNotIn("sk-1234567890abcdef", formatted)
        self.assertNotIn("postgresql://", formatted)
