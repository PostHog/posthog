import os
import sys
import threading

import pytest
from unittest import mock

from parameterized import parameterized

import posthog.web_memory_sampler as sampler


@pytest.mark.skipif(sys.platform != "linux", reason="requires /proc (Linux only)")
def test_current_rss_mb_returns_positive_on_linux():
    rss = sampler.current_rss_mb()
    assert rss is not None
    assert rss > 0


def test_current_rss_mb_handles_missing_proc(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise OSError("no /proc here")

    monkeypatch.setattr("builtins.open", _boom)
    assert sampler.current_rss_mb() is None


def test_sampler_disabled_starts_no_thread(monkeypatch):
    # A non-positive interval must be a no-op so the sampler can be turned off in prod
    # without a deploy, and so it never spawns a thread in environments that don't want it.
    monkeypatch.setattr(sampler, "_sampler_started_pid", None)
    monkeypatch.setenv("WEB_MEMORY_SAMPLE_INTERVAL_SECONDS", "0")

    sampler.start_web_memory_sampler()

    assert sampler._sampler_started_pid is None
    assert not any(t.name == "web-memory-sampler" for t in threading.enumerate())


def test_sampler_rearms_when_guard_inherited_from_another_process(monkeypatch):
    # Unit forks workers from a prototype, so the once-flag is copy-on-write-inherited with
    # the prototype's pid. A worker must re-arm on its own pid and start the thread, not see
    # the inherited value and skip — a plain bool guard here would silently sample nothing.
    started_threads = []

    class _RecordingThread:
        def __init__(self, **kwargs):
            self._name = kwargs["name"]

        def start(self):
            started_threads.append(self._name)

    monkeypatch.setattr(sampler.threading, "Thread", _RecordingThread)
    monkeypatch.setattr(sampler, "_sampler_started_pid", os.getpid() + 1)
    monkeypatch.setenv("WEB_MEMORY_SAMPLE_INTERVAL_SECONDS", "30")

    sampler.start_web_memory_sampler()

    assert sampler._sampler_started_pid == os.getpid()
    assert started_threads == ["web-memory-sampler"]


@parameterized.expand(
    [
        ("rss_present", 123.4, [123.4], 1),
        ("rss_unavailable", None, [], 0),
    ]
)
def test_sample_once_records_gauge_and_log_only_when_rss_available(
    _name, rss_value, expected_gauge_sets, expected_log_count
):
    gauge_sets: list[float] = []
    log_events: list[tuple] = []

    class _RecordingLog:
        def info(self, *args, **kwargs):
            log_events.append((args, kwargs))

    with (
        mock.patch.object(sampler, "current_rss_mb", lambda: rss_value),
        mock.patch.object(sampler.WORKER_RSS_MB, "set", lambda value: gauge_sets.append(value)),
    ):
        sampler._sample_once(_RecordingLog(), "pod-1", "7500")

    assert gauge_sets == expected_gauge_sets
    assert len(log_events) == expected_log_count
