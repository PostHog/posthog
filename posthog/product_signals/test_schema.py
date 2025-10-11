from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import Product
from posthog.product_signals.schema import (
    ProductSignal,
    ProductSignalException,
    ProductSignalSeverity,
    ProductSignalType,
)


class TestProductSignal(BaseTest):
    def test_to_event_properties_basic(self):
        signal = ProductSignal(
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.HIGH,
            title="Test Issue",
            description="Test description",
            source=Product.ERROR_TRACKING,
            distinct_id="team_123",
        )

        props = signal.to_event_properties()

        assert props["$product_signal_type"] == "new_issue"
        assert props["$product_signal_severity"] == "high"
        assert props["$product_signal_title"] == "Test Issue"
        assert props["$product_signal_source"] == "error_tracking"
        assert props["$product_signal_description"] == "Test description"

    def test_to_event_properties_without_description(self):
        signal = ProductSignal(
            signal_type=ProductSignalType.FUNNEL_CONVERSION_RATE_CHANGE,
            severity=ProductSignalSeverity.MEDIUM,
            title="Test Issue",
            source=Product.PRODUCT_ANALYTICS,
            distinct_id="team_456",
        )

        props = signal.to_event_properties()

        assert "$product_signal_description" not in props
        assert props["$product_signal_type"] == "funnel_conversion_rate_change"
        assert props["$product_signal_severity"] == "medium"

    def test_to_event_properties_with_metadata(self):
        signal = ProductSignal(
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.CRITICAL,
            title="Critical Error",
            source=Product.ERROR_TRACKING,
            distinct_id="team_789",
            metadata={
                "error_id": "err_123",
                "affected_users": 150,
                "url": "https://example.com/checkout",
            },
        )

        props = signal.to_event_properties()

        assert props["error_id"] == "err_123"
        assert props["affected_users"] == 150
        assert props["url"] == "https://example.com/checkout"
        assert props["$product_signal_type"] == "new_issue"

    @patch("posthog.product_signals.schema.capture_internal")
    def test_create_signal_success(self, mock_capture_internal):
        mock_capture_internal.return_value = None

        ProductSignal.create(
            team_token="test_token",
            distinct_id="team_123",
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.HIGH,
            title="Test Signal",
            source=Product.ERROR_TRACKING,
            description="Test description",
        )

        mock_capture_internal.assert_called_once()
        call_kwargs = mock_capture_internal.call_args.kwargs

        assert call_kwargs["token"] == "test_token"
        assert call_kwargs["event_name"] == "$product_signal"
        assert call_kwargs["event_source"] == "product_signals"
        assert call_kwargs["distinct_id"] == "team_123"
        assert call_kwargs["process_person_profile"] is False
        assert call_kwargs["properties"]["$product_signal_type"] == "new_issue"
        assert call_kwargs["properties"]["$product_signal_severity"] == "high"
        assert call_kwargs["properties"]["$product_signal_title"] == "Test Signal"

    @patch("posthog.product_signals.schema.capture_internal")
    def test_create_signal_with_timestamp(self, mock_capture_internal):
        mock_capture_internal.return_value = None

        custom_timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        ProductSignal.create(
            team_token="test_token",
            distinct_id="team_456",
            signal_type=ProductSignalType.FUNNEL_CONVERSION_RATE_CHANGE,
            severity=ProductSignalSeverity.MEDIUM,
            title="Funnel Drop",
            source=Product.PRODUCT_ANALYTICS,
            timestamp=custom_timestamp,
        )

        call_kwargs = mock_capture_internal.call_args.kwargs
        assert call_kwargs["timestamp"] == custom_timestamp

    @patch("posthog.product_signals.schema.capture_internal")
    def test_create_signal_with_metadata(self, mock_capture_internal):
        mock_capture_internal.return_value = None

        ProductSignal.create(
            team_token="test_token",
            distinct_id="team_789",
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.CRITICAL,
            title="Critical Bug",
            source=Product.ERROR_TRACKING,
            metadata={
                "error_count": 42,
                "first_seen": "2024-01-01T00:00:00Z",
            },
        )

        call_kwargs = mock_capture_internal.call_args.kwargs
        assert call_kwargs["properties"]["error_count"] == 42
        assert call_kwargs["properties"]["first_seen"] == "2024-01-01T00:00:00Z"

    @patch("posthog.product_signals.schema.capture_exception")
    @patch("posthog.product_signals.schema.capture_internal")
    def test_create_signal_captures_exception_on_error(self, mock_capture_internal, mock_capture_exception):
        mock_capture_internal.side_effect = Exception("Capture failed")

        ProductSignal.create(
            team_token="test_token",
            distinct_id="team_123",
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.HIGH,
            title="Test Signal",
            source=Product.ERROR_TRACKING,
        )

        mock_capture_exception.assert_called_once()
        captured_exception = mock_capture_exception.call_args[0][0]
        assert isinstance(captured_exception, ProductSignalException)
        assert captured_exception.signal_type == ProductSignalType.NEW_ISSUE
        assert captured_exception.severity == ProductSignalSeverity.HIGH
        assert captured_exception.title == "Test Signal"
        assert captured_exception.cause is not None
        assert str(captured_exception.cause) == "Capture failed"


class TestProductSignalException(BaseTest):
    def test_exception_captures_signal_data(self):
        signal = ProductSignal(
            signal_type=ProductSignalType.FUNNEL_CONVERSION_RATE_CHANGE,
            severity=ProductSignalSeverity.CRITICAL,
            title="Test Exception",
            description="Test description",
            source=Product.PRODUCT_ANALYTICS,
            distinct_id="team_999",
            metadata={"key": "value"},
        )

        exception = ProductSignalException(signal)

        assert exception.signal_type == ProductSignalType.FUNNEL_CONVERSION_RATE_CHANGE
        assert exception.severity == ProductSignalSeverity.CRITICAL
        assert exception.title == "Test Exception"
        assert exception.description == "Test description"
        assert exception.distinct_id == "team_999"
        assert exception.metadata == {"key": "value"}

    def test_exception_message_format(self):
        signal = ProductSignal(
            signal_type=ProductSignalType.NEW_ISSUE,
            severity=ProductSignalSeverity.LOW,
            title="Low Priority Signal",
            source=Product.ERROR_TRACKING,
            distinct_id="team_100",
        )

        exception = ProductSignalException(signal)

        assert str(exception) == "ProductSignalException: new_issue [low] - Low Priority Signal"
