from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from prometheus_client import CollectorRegistry, Counter

from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter
from posthog.tasks.exporter import export_asset_direct
from posthog.tasks.exports.failure_handler import (
    FAILURE_TYPE_SYSTEM,
    FAILURE_TYPE_TIMEOUT_GENERATION,
    FAILURE_TYPE_UNKNOWN,
    FAILURE_TYPE_USER,
    classify_failure_type,
    is_user_query_error_type,
)


def get_counter_value(counter: Counter, labels: dict) -> float:
    """Extract the value of a counter with specific labels."""
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") or sample.name == counter._name:
                if all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return 0.0


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


@patch("posthog.tasks.exports.image_exporter.uuid")
class TestExportFailedCounter(APIBaseTest):
    """Tests for Prometheus counter wiring on export failures."""

    def _create_test_counter(self, registry: CollectorRegistry) -> Counter:
        """Create a test counter bound to a fresh registry."""
        return Counter(
            "exporter_task_failed_test",
            "Test counter for export failures",
            labelnames=["type", "failure_type"],
            registry=registry,
        )

    @patch("posthog.tasks.exports.image_exporter.export_image")
    def test_user_error_increments_counter_with_user_label(self, mock_export: MagicMock, mock_uuid: MagicMock) -> None:
        from posthog.hogql.errors import QueryError

        registry = CollectorRegistry()
        test_counter = self._create_test_counter(registry)
        original_counter = exporter.EXPORT_FAILED_COUNTER

        try:
            exporter.EXPORT_FAILED_COUNTER = test_counter
            mock_export.side_effect = QueryError("Bad query")

            asset = ExportedAsset.objects.create(team=self.team, dashboard=None, export_format="image/png")
            export_asset_direct(asset)

            asset.refresh_from_db()
            assert asset.failure_type == "user"
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "user"}) == 1.0
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "system"}) == 0.0
        finally:
            exporter.EXPORT_FAILED_COUNTER = original_counter

    @patch("posthog.tasks.exports.image_exporter.export_image")
    def test_timeout_error_increments_counter_with_timeout_label(
        self, mock_export: MagicMock, mock_uuid: MagicMock
    ) -> None:
        from celery.exceptions import SoftTimeLimitExceeded

        registry = CollectorRegistry()
        test_counter = self._create_test_counter(registry)
        original_counter = exporter.EXPORT_FAILED_COUNTER

        try:
            exporter.EXPORT_FAILED_COUNTER = test_counter
            mock_export.side_effect = SoftTimeLimitExceeded("Task timed out")

            asset = ExportedAsset.objects.create(team=self.team, dashboard=None, export_format="image/png")
            export_asset_direct(asset)

            asset.refresh_from_db()
            assert asset.failure_type == "timeout_generation"
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "timeout_generation"}) == 1.0
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "user"}) == 0.0
        finally:
            exporter.EXPORT_FAILED_COUNTER = original_counter

    @patch("posthog.tasks.exports.image_exporter.export_image")
    def test_unknown_error_increments_counter_with_unknown_label(
        self, mock_export: MagicMock, mock_uuid: MagicMock
    ) -> None:
        registry = CollectorRegistry()
        test_counter = self._create_test_counter(registry)
        original_counter = exporter.EXPORT_FAILED_COUNTER

        try:
            exporter.EXPORT_FAILED_COUNTER = test_counter
            mock_export.side_effect = RuntimeError("Unexpected error")

            asset = ExportedAsset.objects.create(team=self.team, dashboard=None, export_format="image/png")
            export_asset_direct(asset)

            asset.refresh_from_db()
            assert asset.failure_type == "unknown"
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "unknown"}) == 1.0
        finally:
            exporter.EXPORT_FAILED_COUNTER = original_counter

    @patch("posthog.tasks.exports.csv_exporter.export_tabular")
    def test_csv_export_failure_uses_csv_type_label(self, mock_export: MagicMock, mock_uuid: MagicMock) -> None:
        from posthog.hogql.errors import QueryError

        registry = CollectorRegistry()
        test_counter = self._create_test_counter(registry)
        original_counter = exporter.EXPORT_FAILED_COUNTER

        try:
            exporter.EXPORT_FAILED_COUNTER = test_counter
            mock_export.side_effect = QueryError("Bad query")

            asset = ExportedAsset.objects.create(
                team=self.team,
                dashboard=None,
                export_format=ExportedAsset.ExportFormat.CSV,
                export_context={"path": "/api/test"},
            )
            export_asset_direct(asset)

            asset.refresh_from_db()
            assert asset.failure_type == "user"
            assert get_counter_value(test_counter, {"type": "csv", "failure_type": "user"}) == 1.0
            assert get_counter_value(test_counter, {"type": "image", "failure_type": "user"}) == 0.0
        finally:
            exporter.EXPORT_FAILED_COUNTER = original_counter
