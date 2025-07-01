import datetime
from unittest.mock import patch
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client.execute_async import execute_process_query, QueryStatusManager
from posthog.exceptions import ExperimentValidationError, ExperimentDataError, ExperimentCalculationError
from posthog.models import User
from posthog.schema import QueryStatus
from posthog.test.base import APIBaseTest


class TestExperimentAsyncErrorHandling(APIBaseTest):
    """
    Test that ExperimentValidationError is properly handled in async query execution,
    while regular ValidationError is not exposed.
    """

    def setUp(self):
        super().setUp()
        self.query_id = "test-experiment-query-id"
        self.manager = QueryStatusManager(self.query_id, self.team.id)

        # No extra setup needed - we'll handle logging suppression per test

    def _setup_query_status(self, query_id=None):
        """Helper to set up initial query status"""
        if query_id is None:
            query_id = self.query_id
        manager = QueryStatusManager(query_id, self.team.id)
        initial_status = QueryStatus(
            id=query_id,
            team_id=self.team.id,
            start_time=datetime.datetime.now(datetime.UTC),
        )
        manager.store_query_status(initial_status)
        return manager

    def _execute_with_suppressed_logging(self, mock_func, **execute_kwargs):
        """Helper to execute query with suppressed error logging"""
        with (
            patch("posthog.api.services.query.process_query_dict", side_effect=mock_func),
            patch("posthog.clickhouse.client.execute_async.logger.exception"),
            patch("posthog.clickhouse.client.execute_async.capture_exception"),
        ):
            execute_process_query(**execute_kwargs)

    def test_experiment_validation_error_is_exposed_in_async_execution(self):
        """Test that ExperimentValidationError details are properly exposed to users"""
        experiment_error_detail = '{"no-exposures": false, "no-control-variant": true, "no-test-variant": true}'

        def mock_process_query_dict(*args, **kwargs):
            raise ExperimentValidationError(detail=experiment_error_detail)

        # Set up initial query status
        self._setup_query_status()

        # Execute with suppressed logging
        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 123},
            limit_context=None,
            is_query_service=False,
        )

        # Verify the query status was stored with error details
        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        self.assertEqual(query_status.error_message, experiment_error_detail)
        self.assertTrue(query_status.complete)
        self.assertIsNone(query_status.results)

    def test_experiment_validation_error_cleans_django_error_detail_format(self):
        """Test that Django ErrorDetail wrapper is cleaned from ExperimentValidationError"""
        django_error_detail = (
            "[ErrorDetail(string='{\"no-exposures\": false, \"no-control-variant\": true}', code='no-results')]"
        )

        def mock_process_query_dict(*args, **kwargs):
            raise ExperimentValidationError(detail=django_error_detail)

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 123},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        # Should extract just the JSON part
        self.assertEqual(query_status.error_message, '{"no-exposures": false, "no-control-variant": true}')

    def test_regular_validation_error_is_not_exposed_in_async_execution(self):
        """Test that regular ValidationError is not exposed to users (empty error_message)"""

        def mock_process_query_dict(*args, **kwargs):
            raise ValidationError("This is a regular validation error that should not be exposed")

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=None,  # No user, so not staff
            query_id=self.query_id,
            query_json={"kind": "SomeQuery"},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        # Regular ValidationError should not have error_message
        self.assertIsNone(query_status.error_message)
        self.assertTrue(query_status.complete)
        self.assertIsNone(query_status.results)

    def test_staff_user_sees_all_errors_including_validation_error(self):
        """Test that staff users can see all error types including ValidationError"""
        # Create a staff user
        staff_user = User.objects.create_user(
            email="staff@posthog.com", password="password", first_name="Staff", is_staff=True
        )

        def mock_process_query_dict(*args, **kwargs):
            raise ValidationError("This validation error should be visible to staff")

        self._setup_query_status()

        # For staff users, we still want to suppress logging since this is expected behavior
        with (
            patch("posthog.api.services.query.process_query_dict", side_effect=mock_process_query_dict),
            patch("posthog.clickhouse.client.execute_async.logger.exception"),
            patch("posthog.clickhouse.client.execute_async.capture_exception"),
        ):
            execute_process_query(
                team_id=self.team.id,
                user_id=staff_user.id,
                query_id=self.query_id,
                query_json={"kind": "SomeQuery"},
                limit_context=None,
                is_query_service=False,
            )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        # Staff user should see the error message (with Django ErrorDetail format)
        self.assertEqual(
            query_status.error_message,
            "[ErrorDetail(string='This validation error should be visible to staff', code='invalid')]",
        )
        self.assertTrue(query_status.complete)
        self.assertIsNone(query_status.results)

    def test_other_api_exceptions_are_still_exposed(self):
        """Test that other APIException subclasses are still properly exposed"""
        from posthog.exceptions import EstimatedQueryExecutionTimeTooLong

        def mock_process_query_dict(*args, **kwargs):
            raise EstimatedQueryExecutionTimeTooLong("Query too slow")

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "SomeQuery"},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        self.assertEqual(query_status.error_message, "Query too slow")

    def test_experiment_data_error_is_exposed_in_async_execution(self):
        """Test that ExperimentDataError is properly exposed to users"""

        def mock_process_query_dict(*args, **kwargs):
            raise ExperimentDataError("Experiment with id 123 does not exist")

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 123},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        self.assertEqual(query_status.error_message, "Experiment with id 123 does not exist")

    def test_experiment_calculation_error_is_exposed_in_async_execution(self):
        """Test that ExperimentCalculationError is properly exposed to users"""

        def mock_process_query_dict(*args, **kwargs):
            raise ExperimentCalculationError("Failed to calculate Bayesian experiment results: Division by zero")

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 123},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        self.assertEqual(
            query_status.error_message, "Failed to calculate Bayesian experiment results: Division by zero"
        )

    def test_experiment_validation_error_with_various_error_combinations(self):
        """Test ExperimentValidationError with different error key combinations"""
        test_cases = [
            # No exposures only
            '{"no-exposures": true, "no-control-variant": false, "no-test-variant": false}',
            # No control variant only
            '{"no-exposures": false, "no-control-variant": true, "no-test-variant": false}',
            # No test variant only
            '{"no-exposures": false, "no-control-variant": false, "no-test-variant": true}',
            # Multiple errors
            '{"no-exposures": true, "no-control-variant": true, "no-test-variant": true}',
        ]

        for i, error_detail in enumerate(test_cases):
            with self.subTest(case=i):
                query_id = f"test-{i}"
                manager = self._setup_query_status(query_id)

                # Capture error_detail in closure to avoid late binding
                def make_mock(detail):
                    def mock_process_query_dict(*args, **kwargs):
                        raise ExperimentValidationError(detail=detail)

                    return mock_process_query_dict

                mock_func = make_mock(error_detail)

                with (
                    patch("posthog.api.services.query.process_query_dict", side_effect=mock_func),
                    patch("posthog.clickhouse.client.execute_async.logger.exception"),
                    patch("posthog.clickhouse.client.execute_async.capture_exception"),
                ):
                    execute_process_query(
                        team_id=self.team.id,
                        user_id=self.user.id,
                        query_id=query_id,
                        query_json={"kind": "ExperimentQuery", "experiment_id": 123},
                        limit_context=None,
                        is_query_service=False,
                    )

                query_status = manager.get_query_status()
                self.assertTrue(query_status.error)
                self.assertEqual(query_status.error_message, error_detail)

    def test_real_experiment_data_error_in_async_execution(self):
        """Test real ExperimentDataError when experiment doesn't exist"""

        def mock_process_query_dict(*args, **kwargs):
            # Simulate what happens when ExperimentQueryRunner tries to load nonexistent experiment
            from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
            from posthog.schema import ExperimentQuery, ExperimentMeanMetric, EventsNode

            experiment_query = ExperimentQuery(
                experiment_id=99999,  # Non-existent
                metric=ExperimentMeanMetric(source=EventsNode(event="test")),
            )

            # This will raise ExperimentDataError when trying to load the experiment
            ExperimentQueryRunner(query=experiment_query, team=self.team)

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=self.user.id,
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 99999},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        self.assertEqual(query_status.error_message, "Experiment with id 99999 does not exist")

    def test_unhandled_exception_still_hidden_from_users(self):
        """Test that unhandled exceptions (not ExperimentError) are still hidden"""

        def mock_process_query_dict(*args, **kwargs):
            # Simulate an unhandled exception that shouldn't be exposed
            raise AttributeError("'NoneType' object has no attribute 'some_property'")

        self._setup_query_status()

        self._execute_with_suppressed_logging(
            mock_func=mock_process_query_dict,
            team_id=self.team.id,
            user_id=None,  # Non-staff user
            query_id=self.query_id,
            query_json={"kind": "ExperimentQuery", "experiment_id": 123},
            limit_context=None,
            is_query_service=False,
        )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        # Unhandled exceptions should still result in no error message for non-staff
        self.assertIsNone(query_status.error_message)
        self.assertTrue(query_status.complete)
        self.assertIsNone(query_status.results)

    def test_staff_user_sees_unhandled_exceptions(self):
        """Test that staff users can see unhandled exceptions for debugging"""
        # Create a staff user
        staff_user = User.objects.create_user(
            email="staff@posthog.com", password="password", first_name="Staff", is_staff=True
        )

        def mock_process_query_dict(*args, **kwargs):
            raise AttributeError("'NoneType' object has no attribute 'some_property'")

        self._setup_query_status()

        # For staff users, we still want to suppress logging since this is expected behavior
        with (
            patch("posthog.api.services.query.process_query_dict", side_effect=mock_process_query_dict),
            patch("posthog.clickhouse.client.execute_async.logger.exception"),
            patch("posthog.clickhouse.client.execute_async.capture_exception"),
        ):
            execute_process_query(
                team_id=self.team.id,
                user_id=staff_user.id,
                query_id=self.query_id,
                query_json={"kind": "ExperimentQuery", "experiment_id": 123},
                limit_context=None,
                is_query_service=False,
            )

        query_status = self.manager.get_query_status()
        self.assertTrue(query_status.error)
        # Staff user should see the unhandled exception
        self.assertEqual(query_status.error_message, "'NoneType' object has no attribute 'some_property'")
        self.assertTrue(query_status.complete)
        self.assertIsNone(query_status.results)
