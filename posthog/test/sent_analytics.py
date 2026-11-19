from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

import posthoganalytics


@contextmanager
def record_sent_analytics() -> Iterator[list[dict[str, Any]]]:
    sent_events: list[dict[str, Any]] = []
    with patch.multiple(
        posthoganalytics,
        default_client=None,
        disabled=False,
        send=False,
        enable_local_evaluation=False,
        enable_exception_autocapture=False,
        before_send=sent_events.append,
    ):
        yield sent_events
        posthoganalytics.shutdown()
