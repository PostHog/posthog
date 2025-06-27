import pytest
from unittest.mock import Mock, patch, MagicMock
from opentelemetry.trace import Status, StatusCode
from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client.tracing import trace_clickhouse_query, add_clickhouse_span_attributes
from posthog.clickhouse.client.connection import Workload, ClickHouseUser
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HOST


class TestTraceClickhouseQuery:
    """Test the trace_clickhouse_query context manager"""

    def test_basic_tracing_success(self):
        """Test basic successful query tracing"""
        query = "SELECT 1"
        args = {"param": "value"}
        team_id = 123
        workload = Workload.ONLINE
        ch_user = ClickHouseUser.APP
        query_type = "test_query"
        query_id = "test_123"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            # Create a proper context manager mock
            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(
                query=query,
                args=args,
                workload=workload,
                team_id=team_id,
                readonly=True,
                ch_user=ch_user,
                query_type=query_type,
                query_id=query_id,
            ) as _:
                # Simulate some work
                pass

            # Verify span attributes were set correctly
            mock_span.set_attribute.assert_any_call("db.system", "clickhouse")
            mock_span.set_attribute.assert_any_call("db.name", CLICKHOUSE_DATABASE)
            mock_span.set_attribute.assert_any_call("db.user", ch_user.value)
            mock_span.set_attribute.assert_any_call("db.statement", query)
            mock_span.set_attribute.assert_any_call("net.peer.name", CLICKHOUSE_HOST)
            mock_span.set_attribute.assert_any_call("net.peer.port", 9000)
            mock_span.set_attribute.assert_any_call("span.kind", "client")
            mock_span.set_attribute.assert_any_call("clickhouse.workload", workload.value)
            mock_span.set_attribute.assert_any_call("clickhouse.team_id", str(team_id))
            mock_span.set_attribute.assert_any_call("clickhouse.readonly", True)
            mock_span.set_attribute.assert_any_call("clickhouse.query_type", query_type)
            mock_span.set_attribute.assert_any_call("clickhouse.query_id", query_id)
            mock_span.set_attribute.assert_any_call("clickhouse.args_count", 1)
            mock_span.set_attribute.assert_any_call("clickhouse.args_keys", ["param"])

            # Verify success attributes (check StatusCode, not object identity)
            status_call = mock_span.set_status.call_args[0][0]
            assert isinstance(status_call, Status)
            assert status_call.status_code == StatusCode.OK

    def test_tracing_with_list_args(self):
        """Test tracing with list/tuple arguments"""
        query = "INSERT INTO table VALUES"
        args = [1, 2, 3]

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query, args=args):
                pass

            # Verify args_count is set for list args
            mock_span.set_attribute.assert_any_call("clickhouse.args_count", 3)

    def test_tracing_with_no_args(self):
        """Test tracing with no arguments"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query, args=None):
                pass

            # Verify no args-related attributes are set
            args_calls = [call for call in mock_span.set_attribute.call_args_list if "args" in str(call)]
            assert len(args_calls) == 0

    def test_tracing_without_query_id(self):
        """Test tracing without query_id"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query):
                pass

            # Verify query_id attribute is not set
            query_id_calls = [call for call in mock_span.set_attribute.call_args_list if "query_id" in str(call)]
            assert len(query_id_calls) == 0

    def test_tracing_without_team_id(self):
        """Test tracing without team_id"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query, team_id=None):
                pass

            # Verify team_id is set to empty string
            mock_span.set_attribute.assert_any_call("clickhouse.team_id", "")

    def test_tracing_execution_time(self):
        """Test that execution time is recorded"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query):
                # Simulate some work
                pass

            # Verify execution time was recorded
            execution_time_calls = [
                call for call in mock_span.set_attribute.call_args_list if "execution_time_ms" in str(call)
            ]
            assert len(execution_time_calls) == 1

    def test_tracing_error_handling(self):
        """Test tracing when an exception occurs"""
        query = "SELECT 1"
        test_exception = ServerException("Test error", code=500)

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with pytest.raises(ServerException):
                with trace_clickhouse_query(query=query):
                    raise test_exception

            # Verify error attributes were set
            mock_span.set_attribute.assert_any_call("clickhouse.success", False)
            mock_span.set_attribute.assert_any_call("clickhouse.error_type", "ServerException")
            # Accept any error message, but check it contains the exception string
            found = False
            for call in mock_span.set_attribute.call_args_list:
                if call[0][0] == "clickhouse.error_message":
                    found = True
                    assert "Test error" in call[0][1]
                    break
            assert found, "clickhouse.error_message not set"
            # Check StatusCode.ERROR
            status_call = mock_span.set_status.call_args[0][0]
            assert isinstance(status_call, Status)
            assert status_call.status_code == StatusCode.ERROR
            mock_span.record_exception.assert_called_with(test_exception)

    def test_tracing_span_not_recording(self):
        """Test behavior when span is not recording"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = False

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query):
                pass

            # Verify no attributes were set
            assert mock_span.set_attribute.call_count == 0

    def test_tracing_yields_span(self):
        """Test that the context manager yields the span"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query) as span:
                assert span is mock_span

    def test_tracing_default_values(self):
        """Test tracing with default parameter values"""
        query = "SELECT 1"

        with patch("posthog.clickhouse.client.tracing.trace") as mock_trace:
            mock_span = Mock()
            mock_span.is_recording.return_value = True

            mock_context = MagicMock()
            mock_context.__enter__.return_value = mock_span
            mock_context.__exit__.return_value = None

            mock_tracer = Mock()
            mock_tracer.start_as_current_span.return_value = mock_context
            mock_trace.get_tracer.return_value = mock_tracer

            with trace_clickhouse_query(query=query):
                pass

            # Verify default values are used
            mock_span.set_attribute.assert_any_call("clickhouse.workload", Workload.DEFAULT.value)
            mock_span.set_attribute.assert_any_call("clickhouse.readonly", False)
            mock_span.set_attribute.assert_any_call("clickhouse.query_type", "Other")
            mock_span.set_attribute.assert_any_call("db.user", ClickHouseUser.DEFAULT.value)


class TestAddClickhouseSpanAttributes:
    """Test the add_clickhouse_span_attributes helper function"""

    def test_add_attributes_recording_span(self):
        """Test adding attributes to a recording span"""
        mock_span = Mock()
        mock_span.is_recording.return_value = True

        add_clickhouse_span_attributes(mock_span, test_attr="test_value", another_attr=123)

        mock_span.set_attribute.assert_any_call("clickhouse.test_attr", "test_value")
        mock_span.set_attribute.assert_any_call("clickhouse.another_attr", 123)

    def test_add_attributes_non_recording_span(self):
        """Test adding attributes to a non-recording span"""
        mock_span = Mock()
        mock_span.is_recording.return_value = False

        add_clickhouse_span_attributes(mock_span, test_attr="test_value")

        # Verify no attributes were set
        assert mock_span.set_attribute.call_count == 0

    def test_add_attributes_no_attributes(self):
        """Test adding no attributes"""
        mock_span = Mock()
        mock_span.is_recording.return_value = True

        add_clickhouse_span_attributes(mock_span)

        # Verify no attributes were set
        assert mock_span.set_attribute.call_count == 0
