from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import CollectorRegistry, Counter

from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter
from posthog.tasks.exporter import record_export_failure
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


class TestRecordExportFailure(APIBaseTest):
    def test_record_export_failure_updates_asset_and_increments_counter(self) -> None:
        from posthog.hogql.errors import QueryError

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
