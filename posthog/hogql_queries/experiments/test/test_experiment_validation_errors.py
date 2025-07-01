"""
Tests to verify that experiment query runners properly raise ExperimentValidationError
instead of regular ValidationError for experiment-specific validation failures.
"""

import json
from unittest.mock import patch
from django.test import override_settings

from posthog.exceptions import ExperimentValidationError, ExperimentDataError

# Legacy query runners are not tested as they're deprecated in favor of ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
# Only test ExperimentQueryRunner as other query runners are legacy
# Test imports handled in individual test methods


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentValidationErrors(ExperimentQueryRunnerBaseTest):
    """Test that ExperimentQueryRunner raises ExperimentValidationError correctly"""

    def _suppress_expected_logging(self):
        """Context manager to suppress expected error logging during tests"""
        # Since we're testing expected exceptions, suppress the capture_exception calls
        return patch("posthog.exceptions_capture.capture_exception")

    def test_experiment_query_runner_missing_experiment_id(self):
        """Test ExperimentQueryRunner raises ExperimentValidationError for missing experiment_id"""
        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
        from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode

        # Create a valid query but with missing experiment_id
        experiment_query = ExperimentQuery(
            experiment_id=None,  # Missing experiment ID
            metric=ExperimentMeanMetric(source=EventsNode(event="test")),
        )

        with self.assertRaises(ExperimentValidationError) as cm:
            ExperimentQueryRunner(query=experiment_query, team=self.team)

        # Should raise ExperimentValidationError with appropriate message
        self.assertEqual(str(cm.exception.detail), "experiment_id is required")

    def test_experiment_query_runner_nonexistent_experiment(self):
        """Test ExperimentQueryRunner raises ExperimentDataError for nonexistent experiment"""
        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
        from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode

        # Create a query with an experiment ID that doesn't exist
        experiment_query = ExperimentQuery(
            experiment_id=99999,  # Non-existent experiment ID
            metric=ExperimentMeanMetric(source=EventsNode(event="test")),
        )

        with self.assertRaises(ExperimentDataError) as cm:
            ExperimentQueryRunner(query=experiment_query, team=self.team)

        # Should raise ExperimentDataError with appropriate message
        self.assertEqual(str(cm.exception.detail), "Experiment with id 99999 does not exist")

    def test_experiment_query_execution_error_handling(self):
        """Test that query execution errors are wrapped in ExperimentCalculationError"""
        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
        from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode
        from unittest.mock import patch
        from posthog.exceptions import ExperimentCalculationError

        # Create a valid experiment first
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            metric=ExperimentMeanMetric(source=EventsNode(event="test")),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        # Mock execute_hogql_query to raise an exception, with logging suppression
        with (
            patch("posthog.hogql_queries.experiments.experiment_query_runner.execute_hogql_query") as mock_execute,
            self._suppress_expected_logging(),
        ):
            mock_execute.side_effect = Exception("Database connection timeout")

            with self.assertRaises(ExperimentCalculationError) as cm:
                query_runner.calculate()

            # Should wrap the original error with a user-friendly message
            self.assertIn("Failed to execute experiment query", str(cm.exception.detail))
            self.assertIn("Database connection timeout", str(cm.exception.detail))

    def test_bayesian_calculation_error_handling(self):
        """Test that Bayesian calculation errors are wrapped in ExperimentCalculationError"""
        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
        from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode
        from unittest.mock import patch
        from posthog.exceptions import ExperimentCalculationError

        # Create a valid experiment first
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        # Set experiment to use new Bayesian method
        experiment.stats_config = {"use_new_bayesian_method": True}
        experiment.save()

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            metric=ExperimentMeanMetric(source=EventsNode(event="test")),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        query_runner.stats_method = "bayesian"

        # Mock the Bayesian calculation to fail, with logging suppression
        with (
            patch(
                "posthog.hogql_queries.experiments.experiment_query_runner.get_bayesian_experiment_result_new_format"
            ) as mock_bayesian,
            self._suppress_expected_logging(),
        ):
            mock_bayesian.side_effect = ValueError("Insufficient data for Bayesian analysis")

            # Mock the query execution to return some data
            with patch(
                "posthog.hogql_queries.experiments.experiment_query_runner.ExperimentQueryRunner._evaluate_experiment_query"
            ) as mock_query:
                mock_query.return_value = [("control", 10, 5, 2), ("test", 10, 7, 3)]

                with self.assertRaises(ExperimentCalculationError) as cm:
                    query_runner.calculate()

                # Should wrap the calculation error
                self.assertIn("Failed to calculate Bayesian experiment results", str(cm.exception.detail))
                self.assertIn("Insufficient data for Bayesian analysis", str(cm.exception.detail))

    def test_frequentist_calculation_error_handling(self):
        """Test that frequentist calculation errors are wrapped in ExperimentCalculationError"""
        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
        from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode
        from unittest.mock import patch
        from posthog.exceptions import ExperimentCalculationError

        # Create a valid experiment first
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            metric=ExperimentMeanMetric(source=EventsNode(event="test")),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        query_runner.stats_method = "frequentist"

        # Mock the frequentist calculation to fail, with logging suppression
        with (
            patch(
                "posthog.hogql_queries.experiments.experiment_query_runner.get_frequentist_experiment_result_new_format"
            ) as mock_freq,
            self._suppress_expected_logging(),
        ):
            mock_freq.side_effect = ZeroDivisionError("Division by zero in t-test calculation")

            # Mock the query execution to return some data
            with patch(
                "posthog.hogql_queries.experiments.experiment_query_runner.ExperimentQueryRunner._evaluate_experiment_query"
            ) as mock_query:
                mock_query.return_value = [("control", 10, 5, 2), ("test", 10, 7, 3)]

                with self.assertRaises(ExperimentCalculationError) as cm:
                    query_runner.calculate()

                # Should wrap the calculation error
                self.assertIn("Failed to calculate frequentist experiment results", str(cm.exception.detail))
                self.assertIn("Division by zero in t-test calculation", str(cm.exception.detail))

    def test_experiment_validation_error_format_consistency(self):
        """Test that all experiment query runners produce consistent error formats"""
        # This test ensures that our ExperimentValidationError formatting is consistent
        # across all experiment query runners

        test_error_data = {"no-exposures": True, "no-control-variant": False, "no-test-variant": False}

        # Test the custom exception directly
        error = ExperimentValidationError(detail=json.dumps(test_error_data))
        self.assertEqual(error.detail, json.dumps(test_error_data))

        # Test with Django ErrorDetail format (should be cleaned)
        django_format = f"[ErrorDetail(string='{json.dumps(test_error_data)}', code='no-results')]"
        error_cleaned = ExperimentValidationError(detail=django_format)
        self.assertEqual(error_cleaned.detail, json.dumps(test_error_data))
