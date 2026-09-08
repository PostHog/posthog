import gc
import signal
import logging
from collections.abc import Iterator
from contextlib import ExitStack

import pytest
from unittest.mock import patch

from structlog.testing import LogCapture, capture_logs

from posthog.web_memory_probe import install_memory_probe_handler


@pytest.fixture
def installed_probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    previous = signal.getsignal(signal.SIGUSR2)
    monkeypatch.setenv("WEB_MEMORY_PROBE_ENABLED", "true")
    try:
        install_memory_probe_handler()
        yield
    finally:
        signal.signal(signal.SIGUSR2, previous)


def test_disabled_probe_preserves_signal_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_MEMORY_PROBE_ENABLED", raising=False)
    previous = signal.getsignal(signal.SIGUSR2)
    install_memory_probe_handler()
    assert signal.getsignal(signal.SIGUSR2) == previous


def test_overlapping_signals_are_dropped_and_later_probes_work(installed_probe: None) -> None:
    def signal_during_collection(phase: str, info: dict[str, int]) -> None:
        signal.raise_signal(signal.SIGUSR2)

    gc.callbacks.append(signal_during_collection)
    try:
        with capture_logs() as events:
            signal.raise_signal(signal.SIGUSR2)
    finally:
        gc.callbacks.remove(signal_during_collection)

    assert [event["event"] for event in events] == ["web_memory_probe"]
    with capture_logs() as events:
        signal.raise_signal(signal.SIGUSR2)
    assert [event["event"] for event in events] == ["web_memory_probe"]


@pytest.mark.parametrize("failure", ["collection", "diagnostic_logging", "error_logging"])
def test_probe_failure_does_not_escape_and_later_probes_work(installed_probe: None, failure: str) -> None:
    with capture_logs(), ExitStack() as patches:
        if failure == "diagnostic_logging":
            patches.enter_context(patch.object(LogCapture, "__call__", side_effect=RuntimeError("logging failed")))
        else:
            patches.enter_context(patch.object(gc, "collect", side_effect=RuntimeError("collection failed")))
            if failure == "error_logging":
                patches.enter_context(patch.object(logging.Logger, "exception", side_effect=RuntimeError("log failed")))
        signal.raise_signal(signal.SIGUSR2)

    with capture_logs() as events:
        signal.raise_signal(signal.SIGUSR2)
    assert [event["event"] for event in events] == ["web_memory_probe"]
