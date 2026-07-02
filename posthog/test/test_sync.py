from unittest import mock

from posthog.sync import database_sync_to_async_pool


class _Boom(Exception):
    pass


async def test_pool_call_force_closes_connections_when_wrapped_call_raises():
    fake_conn = mock.Mock()

    def boom() -> None:
        raise _Boom()

    with (
        mock.patch("posthog.sync.settings") as fake_settings,
        mock.patch("posthog.sync.connections") as fake_connections,
        mock.patch("posthog.sync.close_old_connections"),
    ):
        fake_settings.TEST = False
        fake_connections.all.return_value = [fake_conn]

        try:
            await database_sync_to_async_pool(boom)()
        except _Boom:
            pass
        else:
            raise AssertionError("expected _Boom to propagate")

    fake_connections.all.assert_called_once_with(initialized_only=True)
    fake_conn.close.assert_called_once_with()


async def test_pool_call_does_not_force_close_connections_on_success():
    fake_conn = mock.Mock()

    with (
        mock.patch("posthog.sync.settings") as fake_settings,
        mock.patch("posthog.sync.connections") as fake_connections,
        mock.patch("posthog.sync.close_old_connections"),
    ):
        fake_settings.TEST = False
        fake_connections.all.return_value = [fake_conn]

        result = await database_sync_to_async_pool(lambda: "ok")()

    assert result == "ok"
    fake_conn.close.assert_not_called()
