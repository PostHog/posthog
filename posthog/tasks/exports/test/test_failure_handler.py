import time
from contextlib import contextmanager

import pytest
from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from prometheus_client import CollectorRegistry, Counter

from posthog.hogql.errors import QueryError

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter
from posthog.tasks.exporter import record_export_failure
from posthog.tasks.exports import image_exporter
from posthog.tasks.exports.failure_handler import (
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
    classify_failure_type,
    is_user_query_error_type,
)

from ee.tasks.subscriptions import subscription_utils


def get_counter_value(counter: Counter, labels: dict) -> float:
    """Get counter value using the _metrics dict directly (works across threads)."""
    label_values = tuple(str(labels.get(label, "")) for label in counter._labelnames)
    metric = counter._metrics.get(label_values)
    if metric is None:
        return 0.0
    value_container = getattr(metric, "_value", None)
    return value_container.get() if value_container else 0.0


class TestRecordExportFailure(APIBaseTest):
    def test_record_export_failure_updates_asset_and_increments_counter(self) -> None:
        registry = CollectorRegistry()
        test_counter = Counter(
            "exporter_task_failed_test",
            "Test counter",
            labelnames=["type", "failure_type"],
            registry=registry,
        )

        asset = ExportedAsset.objects.create(
            team=self.team,
            dashboard=None,
            export_format=ExportedAsset.ExportFormat.PNG,
        )
        exception = QueryError("Bad query")

        with patch.object(exporter, "EXPORT_FAILED_COUNTER", test_counter):
            record_export_failure(asset, exception)

        asset.refresh_from_db()
        assert asset.failure_type == FAILURE_TYPE_USER
        assert asset.exception_type == "QueryError"
        assert asset.exception == "Bad query"
        assert (
            get_counter_value(test_counter, {"type": ExportedAsset.ExportFormat.PNG, "failure_type": FAILURE_TYPE_USER})
            == 1.0
        )


class TestExportAssetCounters(APIBaseTest):
    """Tests verifying success/failure counters are incremented correctly by export_asset."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = CollectorRegistry()
        self.success_counter = Counter("test_success", "Test", labelnames=["type"], registry=self.registry)
        self.failed_counter = Counter(
            "test_failed", "Test", labelnames=["type", "failure_type"], registry=self.registry
        )
        self.asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
        )

    @parameterized.expand(
        [
            # (error, is_final_attempt, failure_type, expected_success, expected_failure, expects_exception)
            (None, None, FAILURE_TYPE_USER, 1.0, 0.0, False),
            (QueryError("Invalid query"), None, FAILURE_TYPE_USER, 0.0, 1.0, False),
            (CHQueryErrorTooManySimultaneousQueries("err"), False, FAILURE_TYPE_SYSTEM, 0.0, 0.0, True),
            (CHQueryErrorTooManySimultaneousQueries("err"), True, FAILURE_TYPE_SYSTEM, 0.0, 1.0, True),
        ],
        name_func=lambda func,
        num,
        params: f"{func.__name__}_{['success', 'non_retryable', 'retryable_non_final', 'retryable_final'][int(num)]}",
    )
    def test_export_counter_behavior(
        self, error, is_final_attempt, failure_type, expected_success, expected_failure, expects_exception
    ) -> None:
        """Verify success/failure counters increment correctly based on export outcome."""
        from contextlib import nullcontext

        final_attempt_patch = (
            patch("posthog.tasks.exporter._is_final_export_attempt", return_value=is_final_attempt)
            if is_final_attempt is not None
            else nullcontext()
        )
        exception_context = pytest.raises(type(error)) if expects_exception and error else nullcontext()

        with (
            patch("posthog.tasks.exports.image_exporter.export_image", side_effect=error),
            patch.object(exporter, "EXPORT_SUCCEEDED_COUNTER", self.success_counter),
            patch.object(exporter, "EXPORT_FAILED_COUNTER", self.failed_counter),
            final_attempt_patch,
            exception_context,
        ):
            exporter.export_asset(self.asset.id)

        assert get_counter_value(self.success_counter, {"type": ExportedAsset.ExportFormat.PNG}) == expected_success
        assert (
            get_counter_value(
                self.failed_counter, {"type": ExportedAsset.ExportFormat.PNG, "failure_type": failure_type}
            )
            == expected_failure
        )


class TestIsUserQueryErrorType(TestCase):
    @parameterized.expand(
        [
            # User query errors - should return True
            ("QueryError", True),
            ("SyntaxError", True),
            ("CHQueryErrorIllegalAggregation", True),
            ("CHQueryErrorIllegalTypeOfArgument", True),
            ("CHQueryErrorNoCommonType", True),
            ("CHQueryErrorNotAnAggregate", True),
            ("CHQueryErrorTypeMismatch", True),
            ("CHQueryErrorUnknownFunction", True),
            ("ClickHouseQueryTimeOut", True),
            ("ClickHouseQueryMemoryLimitExceeded", True),
            # Non-user errors - should return False
            ("TimeoutError", False),
            ("ValueError", False),
            ("CHQueryErrorS3Error", False),
            ("CHQueryErrorTooManySimultaneousQueries", False),
            ("ClickHouseAtCapacity", False),
            ("ConcurrencyLimitExceeded", False),
            (None, False),
            ("", False),
        ]
    )
    def test_is_user_query_error_type(self, exception_type: str | None, expected: bool) -> None:
        assert is_user_query_error_type(exception_type) == expected


class TestClassifyFailureType(TestCase):
    @parameterized.expand(
        [
            # Timeout errors
            ("SoftTimeLimitExceeded", FAILURE_TYPE_TIMEOUT_GENERATION),
            ("TimeoutError", FAILURE_TYPE_TIMEOUT_GENERATION),
            # User errors (from USER_QUERY_ERRORS)
            ("QueryError", FAILURE_TYPE_USER),
            ("SyntaxError", FAILURE_TYPE_USER),
            ("CHQueryErrorIllegalAggregation", FAILURE_TYPE_USER),
            ("ClickHouseQueryTimeOut", FAILURE_TYPE_USER),
            ("ClickHouseQueryMemoryLimitExceeded", FAILURE_TYPE_USER),
            # System errors (from EXCEPTIONS_TO_RETRY)
            ("CHQueryErrorS3Error", FAILURE_TYPE_SYSTEM),
            ("CHQueryErrorTooManySimultaneousQueries", FAILURE_TYPE_SYSTEM),
            ("OperationalError", FAILURE_TYPE_SYSTEM),
            ("ClickHouseAtCapacity", FAILURE_TYPE_SYSTEM),
            # Unknown errors
            ("ValueError", FAILURE_TYPE_UNKNOWN),
            ("RuntimeError", FAILURE_TYPE_UNKNOWN),
            ("", FAILURE_TYPE_UNKNOWN),
        ]
    )
    def test_classify_failure_type(self, exception_type: str, expected: str) -> None:
        assert classify_failure_type(exception_type) == expected


@pytest.mark.django_db(transaction=True)
class TestGenerateAssetsAsyncCounters:
    """Tests verifying success/failure counters are incremented correctly by generate_assets_async."""

    @pytest.fixture
    def subscription(self, db, django_user_model):
        """Create test data for async export tests."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from posthog.models.dashboard import Dashboard
        from posthog.models.dashboard_tile import DashboardTile
        from posthog.models.insight import Insight
        from posthog.models.organization import Organization
        from posthog.models.subscription import Subscription
        from posthog.models.team import Team

        organization = Organization.objects.create(name="Test Org for Async")
        team = Team.objects.create(organization=organization, name="Test Team for Async")
        user = django_user_model.objects.create(email="async-test@posthog.com")
        user.join(organization=organization)

        dashboard = Dashboard.objects.create(team=team, name="test dashboard", created_by=user)
        insight = Insight.objects.create(team=team, short_id="async123", name="Test insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        subscription = Subscription.objects.create(
            team=team,
            dashboard=dashboard,
            created_by=user,
            target_type="email",
            target_value="test@example.com",
            frequency="daily",
            interval=1,
            start_date=datetime(2022, 1, 1, 9, 0).replace(tzinfo=ZoneInfo("UTC")),
        )

        yield subscription

        subscription.delete()
        DashboardTile.objects.filter(dashboard=dashboard).delete()
        insight.delete()
        dashboard.delete()
        user.delete()
        team.delete()
        organization.delete()

    @staticmethod
    @contextmanager
    def _patch_export_image(mock: MagicMock):
        """Context manager to patch image_exporter.export_image across thread boundaries."""
        original = image_exporter.export_image
        image_exporter.export_image = mock
        try:
            yield mock
        finally:
            image_exporter.export_image = original

    @staticmethod
    def _get_success_counter_value() -> float:
        return get_counter_value(exporter.EXPORT_SUCCEEDED_COUNTER, {"type": ExportedAsset.ExportFormat.PNG})

    @staticmethod
    def _get_failed_counter_value(failure_type: str) -> float:
        return get_counter_value(
            exporter.EXPORT_FAILED_COUNTER, {"type": ExportedAsset.ExportFormat.PNG, "failure_type": failure_type}
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error,failure_type,expected_success_delta,expected_failure_delta,is_timeout",
        [
            (None, FAILURE_TYPE_USER, 1.0, 0.0, False),
            (QueryError("Invalid query"), FAILURE_TYPE_USER, 0.0, 1.0, False),
            (CHQueryErrorTooManySimultaneousQueries("Too many queries"), FAILURE_TYPE_SYSTEM, 0.0, 1.0, False),
            (None, FAILURE_TYPE_TIMEOUT_GENERATION, 0.0, 1.0, True),
        ],
        ids=["success", "user_error", "system_error", "timeout"],
    )
    async def test_export_counter_behavior(
        self, subscription, settings, error, failure_type, expected_success_delta, expected_failure_delta, is_timeout
    ) -> None:
        if is_timeout:

            def slow_export(*args, **kwargs):
                time.sleep(10)

            side_effect = slow_export
        else:
            side_effect = error

        mock_export_image = MagicMock(side_effect=side_effect)

        with (
            patch("ee.tasks.subscriptions.subscription_utils.get_asset_generation_timeout_metric"),
            patch("ee.tasks.subscriptions.subscription_utils.get_asset_generation_duration_metric"),
            self._patch_export_image(mock_export_image),
        ):
            success_before = self._get_success_counter_value()
            failed_before = self._get_failed_counter_value(failure_type)

            if is_timeout:
                # Need > 2 min because export_timeout = (TEMPORAL_TASK_TIMEOUT_MINUTES * 60) - 120
                # 2.05 gives 3-second timeout, slow_export sleeps for 10s to trigger timeout
                settings.TEMPORAL_TASK_TIMEOUT_MINUTES = 2.05

            await subscription_utils.generate_assets_async(subscription, max_asset_count=1)

            success_after = self._get_success_counter_value()
            failed_after = self._get_failed_counter_value(failure_type)

            assert mock_export_image.called
            assert success_after - success_before == expected_success_delta
            assert failed_after - failed_before == expected_failure_delta
