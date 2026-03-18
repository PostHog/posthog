from __future__ import annotations

from unittest.mock import MagicMock, patch

import grpc


class TestChannelStateMonitor:
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_tracks_state_transition(self, mock_conn_hist, mock_transitions, mock_state_enum):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        _ChannelStateMonitor(channel, "test-client")

        channel.subscribe.assert_called_once()
        callback = channel.subscribe.call_args[0][0]

        callback(grpc.ChannelConnectivity.IDLE)

        mock_state_enum.labels.assert_called_with(client_name="test-client")
        mock_state_enum.labels.return_value.state.assert_called_with("IDLE")
        mock_transitions.labels.assert_called_with(from_state="NONE", to_state="IDLE", client_name="test-client")

    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_tracks_connection_establishment_latency(self, mock_conn_hist, mock_transitions, mock_state_enum):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        _ChannelStateMonitor(channel, "test-client")
        callback = channel.subscribe.call_args[0][0]

        callback(grpc.ChannelConnectivity.CONNECTING)
        mock_conn_hist.labels.return_value.observe.assert_not_called()

        callback(grpc.ChannelConnectivity.READY)
        mock_conn_hist.labels.assert_called_with(client_name="test-client")
        mock_conn_hist.labels.return_value.observe.assert_called_once()
        latency = mock_conn_hist.labels.return_value.observe.call_args[0][0]
        assert latency >= 0

    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_does_not_record_latency_on_transient_failure(self, mock_conn_hist, mock_transitions, mock_state_enum):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        _ChannelStateMonitor(channel, "test-client")
        callback = channel.subscribe.call_args[0][0]

        callback(grpc.ChannelConnectivity.CONNECTING)
        callback(grpc.ChannelConnectivity.TRANSIENT_FAILURE)

        mock_conn_hist.labels.return_value.observe.assert_not_called()

    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_does_not_record_latency_for_ready_without_connecting(
        self, mock_conn_hist, mock_transitions, mock_state_enum
    ):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        _ChannelStateMonitor(channel, "test-client")
        callback = channel.subscribe.call_args[0][0]

        callback(grpc.ChannelConnectivity.READY)

        mock_conn_hist.labels.return_value.observe.assert_not_called()

    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_tracks_reconnection_latency(self, mock_conn_hist, mock_transitions, mock_state_enum):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        _ChannelStateMonitor(channel, "test-client")
        callback = channel.subscribe.call_args[0][0]

        # First connection
        callback(grpc.ChannelConnectivity.CONNECTING)
        callback(grpc.ChannelConnectivity.READY)
        assert mock_conn_hist.labels.return_value.observe.call_count == 1

        # Disconnect and reconnect
        callback(grpc.ChannelConnectivity.IDLE)
        callback(grpc.ChannelConnectivity.CONNECTING)
        callback(grpc.ChannelConnectivity.READY)
        assert mock_conn_hist.labels.return_value.observe.call_count == 2

    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL")
    @patch("posthog.personhog_client.client.PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS")
    def test_close_unsubscribes(self, mock_conn_hist, mock_transitions, mock_state_enum):
        from posthog.personhog_client.client import _ChannelStateMonitor

        channel = MagicMock()
        monitor = _ChannelStateMonitor(channel, "test-client")
        monitor.close()

        channel.unsubscribe.assert_called_once()
