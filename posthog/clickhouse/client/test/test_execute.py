import pytest
from unittest.mock import MagicMock, Mock, patch

from clickhouse_driver.errors import NetworkError, ServerException, SocketTimeoutError
from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.errors import is_transient_clickhouse_error


def _client_context_manager(client: Mock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    return cm


class TestIsTransientClickhouseError:
    @parameterized.expand(
        [
            (EOFError("Unexpected EOF while reading bytes"), True),
            (ConnectionResetError(), True),
            (NetworkError("connection reset"), True),
            # A read timeout usually means the query is genuinely slow — retrying just adds load.
            (SocketTimeoutError(), False),
            # A server-returned error is about the query, not the connection.
            (ServerException("bad query", code=241), False),
            (ValueError("nope"), False),
        ]
    )
    def test_classification(self, error: Exception, expected: bool) -> None:
        assert is_transient_clickhouse_error(error) is expected


class TestSyncExecuteTransientRetry:
    def test_retries_once_on_dropped_socket_and_succeeds(self) -> None:
        client = Mock()
        client.execute.side_effect = [EOFError("Unexpected EOF while reading bytes"), [(1,)]]

        with patch(
            "posthog.clickhouse.client.execute.get_client_from_pool",
            return_value=_client_context_manager(client),
        ):
            result = sync_execute("SELECT 1", flush=False, retry_on_transient_error=True)

        assert result == [(1,)]
        assert client.execute.call_count == 2

    def test_does_not_retry_without_opt_in(self) -> None:
        client = Mock()
        client.execute.side_effect = EOFError("Unexpected EOF while reading bytes")

        with patch(
            "posthog.clickhouse.client.execute.get_client_from_pool",
            return_value=_client_context_manager(client),
        ):
            with pytest.raises(EOFError):
                sync_execute("SELECT 1", flush=False)

        assert client.execute.call_count == 1

    def test_does_not_retry_non_transient_error(self) -> None:
        client = Mock()
        # Unknown code wraps to an InternalCHQueryError (still a ServerException) rather than a
        # short-circuited APIException, keeping the assertion about retry behavior, not wrapping.
        client.execute.side_effect = ServerException("bad query", code=999)

        with patch(
            "posthog.clickhouse.client.execute.get_client_from_pool",
            return_value=_client_context_manager(client),
        ):
            with pytest.raises(ServerException):
                sync_execute("SELECT 1", flush=False, retry_on_transient_error=True)

        assert client.execute.call_count == 1
