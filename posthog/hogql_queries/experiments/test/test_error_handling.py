"""Tests for experiment error handling decorator and error message mapping."""

from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from rest_framework.exceptions import ErrorDetail, ValidationError

from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded
from posthog.hogql_queries.experiments.error_handling import (
    ERROR_TYPE_TO_CODE,
    experiment_error_handler,
    get_user_friendly_message,
)


class TestExperimentErrorHandling(BaseTest):
    def test_get_user_friendly_message_for_memory_limit_exceeded(self):
        """Test that ClickHouseQueryMemoryLimitExceeded gets a user-friendly message."""
        error = ClickHouseQueryMemoryLimitExceeded()
        message = get_user_friendly_message(error)

        self.assertIsNotNone(message)
        self.assertEqual(
            message,
            "This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.",
        )

    def test_get_user_friendly_message_for_unmapped_error(self):
        """Test that unmapped errors return None."""
        error = RuntimeError("Some unexpected error")
        message = get_user_friendly_message(error)

        self.assertIsNone(message)

    @patch("posthog.hogql_queries.experiments.error_handling.capture_exception")
    def test_decorator_converts_memory_limit_exception(self, mock_capture):
        """Test that the decorator converts ClickHouseQueryMemoryLimitExceeded to ValidationError."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        mock_self = Mock()
        mock_self.experiment_id = None  # Ensure this is None so the fallback to experiment.id is used
        mock_experiment = Mock()
        mock_experiment.id = 123
        mock_self.experiment = mock_experiment
        mock_self.metric = None
        mock_self.user_facing = True

        with self.assertRaises(ValidationError) as context:
            failing_method(mock_self)

        # ValidationError.detail can be a list or dict, check it's a list first
        self.assertIsInstance(context.exception.detail, list)

        # Cast to list for type checker
        detail_list = cast(list[ErrorDetail], context.exception.detail)

        self.assertEqual(
            str(detail_list[0]),
            "This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.",
        )
        # Verify error code is set correctly
        # In DRF, the code is stored in the ErrorDetail object, not directly on the exception
        self.assertIsInstance(detail_list[0], ErrorDetail)
        self.assertEqual(detail_list[0].code, "memory_limit_exceeded")

        # Verify exception was captured with correct properties
        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        self.assertIsInstance(call_args[0][0], ClickHouseQueryMemoryLimitExceeded)
        self.assertEqual(call_args[1]["additional_properties"]["experiment_id"], 123)
        self.assertEqual(call_args[1]["additional_properties"]["query_runner"], "Mock")

    @patch("posthog.hogql_queries.experiments.error_handling.capture_exception")
    def test_decorator_captures_query_runner_name(self, mock_capture):
        """Test that the decorator captures the query runner class name."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        class ExperimentExposuresQueryRunner:
            def __init__(self):
                self.experiment = Mock(id=456)
                self.metric = None
                self.user_facing = True

        runner = ExperimentExposuresQueryRunner()

        with self.assertRaises(ValidationError):
            failing_method(runner)

        mock_capture.assert_called_once()
        additional_props = mock_capture.call_args[1]["additional_properties"]
        self.assertEqual(additional_props["query_runner"], "ExperimentExposuresQueryRunner")
        self.assertEqual(additional_props["experiment_id"], 456)

    @patch("posthog.hogql_queries.experiments.error_handling.capture_exception")
    def test_decorator_does_not_convert_for_non_user_facing(self, mock_capture):
        """Test that the decorator doesn't convert exceptions when user_facing=False."""

        @experiment_error_handler
        def failing_method(self):
            raise ClickHouseQueryMemoryLimitExceeded()

        mock_self = Mock()
        mock_self.experiment = Mock(id=123)
        mock_self.metric = None
        mock_self.user_facing = False

        # Should re-raise the original exception
        with self.assertRaises(ClickHouseQueryMemoryLimitExceeded):
            failing_method(mock_self)

        # Should still capture for internal tracking
        mock_capture.assert_called_once()

    def test_error_type_to_code_mapping(self):
        """Test that ClickHouseQueryMemoryLimitExceeded has a code mapping."""
        self.assertIn(ClickHouseQueryMemoryLimitExceeded, ERROR_TYPE_TO_CODE)
        self.assertEqual(ERROR_TYPE_TO_CODE[ClickHouseQueryMemoryLimitExceeded], "memory_limit_exceeded")
