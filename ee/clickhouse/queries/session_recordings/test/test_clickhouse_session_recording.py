from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import ClickhouseSessionRecording
from posthog.queries.session_recordings.test.test_session_recording import factory_session_recording_test
from posthog.test.base import ClickhouseTestMixin


class TestClickhouseSessionRecording(ClickhouseTestMixin, factory_session_recording_test(ClickhouseSessionRecording)):  # type: ignore
    pass
