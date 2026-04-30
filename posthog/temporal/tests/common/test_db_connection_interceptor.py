import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import connection

from asgiref.sync import sync_to_async
from temporalio.worker import ExecuteActivityInput

from posthog.temporal.common.db_connection_interceptor import (
    DbConnectionInterceptor,
    _DbConnectionActivityInboundInterceptor,
)
from posthog.temporal.common.interceptor import ALL_TASK_QUEUES, is_task_queue_supported


class TestDbConnectionInterceptor:
    def test_applies_to_all_task_queues(self):
        assert isinstance(DbConnectionInterceptor.task_queue, type(ALL_TASK_QUEUES))
        assert is_task_queue_supported("any-queue", DbConnectionInterceptor) is True

    def test_intercept_activity_returns_inbound_interceptor(self):
        interceptor = DbConnectionInterceptor()
        next_interceptor = MagicMock()
        result = interceptor.intercept_activity(next_interceptor)
        assert isinstance(result, _DbConnectionActivityInboundInterceptor)


@pytest.mark.asyncio
class TestDbConnectionActivityInboundInterceptor:
    @pytest.mark.parametrize(
        "side_effect,return_value",
        [
            (None, "ok"),
            (ValueError("boom"), None),
        ],
    )
    async def test_closes_connections_regardless_of_outcome(self, side_effect, return_value):
        mock_input = MagicMock(spec=ExecuteActivityInput)

        next_interceptor = AsyncMock()
        next_interceptor.execute_activity.side_effect = side_effect
        next_interceptor.execute_activity.return_value = return_value

        interceptor = _DbConnectionActivityInboundInterceptor(next_interceptor)

        with patch("posthog.temporal.common.db_connection_interceptor.close_old_connections") as mock_close:
            if side_effect is not None:
                with pytest.raises(type(side_effect)):
                    await interceptor.execute_activity(mock_input)
            else:
                result = await interceptor.execute_activity(mock_input)
                assert result == return_value

        assert mock_close.call_count == 2
        next_interceptor.execute_activity.assert_awaited_once_with(mock_input)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dead_django_connection_is_closed_by_interceptor():
    """Real-DB integration test: an unusable Django connection is evicted by the interceptor.

    Marks the default connection's ``errors_occurred`` flag — the signal Django itself
    uses to decide a connection should be discarded on the next
    ``close_if_unusable_or_obsolete()`` call. After the interceptor runs, the underlying
    driver connection should be ``None``.

    - ``transaction=True`` is required because ``close_if_unusable_or_obsolete``
      short-circuits inside an atomic block.
    - The interceptor always routes ``close_old_connections`` through ``sync_to_async``,
      so we set up and inspect the connection via ``sync_to_async`` as well to ensure
      both sides land in the same asgiref ``Local`` context.
    """

    def open_and_mark_unusable() -> None:
        connection.ensure_connection()
        assert connection.connection is not None
        connection.errors_occurred = True

    await sync_to_async(open_and_mark_unusable)()

    mock_input = MagicMock(spec=ExecuteActivityInput)
    next_interceptor = AsyncMock()
    next_interceptor.execute_activity.return_value = None

    interceptor = _DbConnectionActivityInboundInterceptor(next_interceptor)
    await interceptor.execute_activity(mock_input)

    def assert_connection_closed() -> None:
        assert connection.connection is None

    await sync_to_async(assert_connection_closed)()
