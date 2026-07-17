from unittest.mock import patch

from django.test import SimpleTestCase

import structlog
from parameterized import parameterized
from structlog.processors import EventRenamer

from posthog.exceptions_capture import capture_exception


class TestCaptureException(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Reproduce the temporal-worker structlog config, where EventRenamer("msg")
        # pops the "event" key. structlog omits that key entirely when the event is
        # None, so logging with a None event used to blow up with KeyError('event').
        saved = structlog.get_config()
        self.addCleanup(structlog.configure, **saved)
        structlog.configure(processors=[EventRenamer("msg"), structlog.processors.KeyValueRenderer()])

    @parameterized.expand([("no_api_key", None), ("with_api_key", "phc_test")])
    def test_capture_exception_without_error_does_not_crash(self, _name: str, api_key: str | None) -> None:
        with (
            patch("posthoganalytics.api_key", api_key),
            patch("posthoganalytics.capture_exception", return_value="event-uuid"),
        ):
            # Must not raise KeyError('event') from EventRenamer.
            capture_exception(additional_properties={"ticket_id": "123"})
