import sys
import json
import subprocess
from dataclasses import replace

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.temporal.common.memory_profiler import profile_worker_memory
from posthog.temporal.common.memory_profiler_process import MemoryProfilerConfig

NO_READER = """
import os
import sys
import json
import socket
with socket.socket() as reservation:
    reservation.bind(('127.0.0.1', 0))
    port = reservation.getsockname()[1]
with socket.socket(fileno=int(sys.argv[1])) as control:
    control.sendall(json.dumps({'stream_port': port, 'metrics_port': 0, 'collector_pid': os.getpid()}).encode() + b'\\n')
    control.recv(1)
"""

WORKER = """
import gc
import os
import sys
import json
import time
import signal
import subprocess
import urllib.request
from unittest.mock import patch
from posthog.temporal.common.memory_profiler import MemoryProfiler, MemoryProfilerConfig

mode = sys.argv[1]
profiler = MemoryProfiler(MemoryProfilerConfig(
    metrics_host='127.0.0.1', metrics_port=0,
    snapshot_interval_seconds=0.05, log_interval_seconds=0.05,
    watchdog_timeout_seconds=1, startup_timeout_seconds=0.2 if mode == 'missing_reader' else 5,
    collector_max_rss_mb=1 if mode == 'memory_limit' else 256,
    native_traces=mode == 'native',
))

def allocate_payload():
    return bytearray(8 * 1024 * 1024)

def cycle():
    payload = allocate_payload()
    retained = [payload]
    retained.append(retained)

def snapshot_until(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f'http://127.0.0.1:{profiler.metrics_port}/memory/allocations', timeout=2) as response:
            summary = json.load(response)
        if predicate(summary):
            return summary
    raise AssertionError(summary)

def payload_bytes(summary):
    return sum(group['bytes'] for group in summary['top_stacks']
               if any(frame['function'] == 'allocate_payload' for frame in group['stack']))

if mode == 'missing_reader':
    original_popen = subprocess.Popen
    def without_reader(command, **kwargs):
        return original_popen([sys.executable, '-c', sys.argv[2], command[4]], **kwargs)
    try:
        with patch('posthog.temporal.common.memory_profiler.subprocess.Popen', side_effect=without_reader):
            try:
                profiler.start()
            except TimeoutError:
                pass
            else:
                raise AssertionError('Missing reader did not time out')
    finally:
        profiler.stop()
    assert profiler.supervisor.poll() is not None
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert len(allocate_payload()) == 8 * 1024 * 1024
    sys.exit(0)

try:
    profiler.start()
    if mode != 'memory_limit':
        snapshot_until(lambda summary: summary['stream_active'])
    if mode in ('lifecycle', 'native'):
        gc.disable()
        payload = allocate_payload()
        allocated = snapshot_until(lambda summary: payload_bytes(summary) >= 8 * 1024 * 1024)
        assert allocated['outstanding_bytes'] >= payload_bytes(allocated)
        assert len(allocated['top_stacks']) <= 20
        if mode == 'native':
            assert all('native_stack' in group for group in allocated['top_stacks'])
        with urllib.request.urlopen(f'http://127.0.0.1:{profiler.metrics_port}/metrics', timeout=2) as response:
            metrics = response.read().decode()
        assert 'memray_stream_active 1.0' in metrics
        assert 'memray_tracked_outstanding_bytes' in metrics
        assert 'age_band' not in metrics
        del payload
        snapshot_until(lambda summary: payload_bytes(summary) == 0)
        cycle()
        snapshot_until(lambda summary: payload_bytes(summary) >= 8 * 1024 * 1024)
        gc.collect()
        released = snapshot_until(lambda summary: payload_bytes(summary) == 0)
        assert released['observed_peak_bytes'] >= allocated['outstanding_bytes']
    else:
        if mode != 'memory_limit':
            sig = signal.SIGSTOP if mode == 'stalled' else signal.SIGKILL
            os.kill(profiler.collector_pid, sig)
        if mode == 'stalled':
            for index in range(5_000_000):
                temporary = bytearray(4096)
                del temporary
        failed = snapshot_until(lambda summary: not summary['stream_active'] and summary['stop_reason'] != 'starting')
        assert failed['stop_reason'] in ('collector_timeout', 'collector_exited', 'stream_backpressure', 'collector_memory_limit')
        timestamp = failed['snapshot_timestamp_seconds']
        assert snapshot_until(lambda summary: not summary['stream_active'])['snapshot_timestamp_seconds'] == timestamp
        with urllib.request.urlopen(f'http://127.0.0.1:{profiler.metrics_port}/metrics', timeout=2) as response:
            assert 'memray_stream_active 0.0' in response.read().decode()
        assert len(allocate_payload()) == 8 * 1024 * 1024
finally:
    profiler.stop()
assert profiler.supervisor.poll() is not None
try:
    os.kill(profiler.collector_pid, 0)
except ProcessLookupError:
    pass
else:
    raise AssertionError('Collector survived shutdown')
"""


@override_settings(TEMPORAL_MEMRAY_ENABLED=False)
def test_disabled_profiler_does_not_start_processes() -> None:
    with patch("posthog.temporal.common.memory_profiler.MemoryProfiler") as profiler:
        with profile_worker_memory("test-queue"):
            pass
        profiler.assert_not_called()


@pytest.mark.parametrize("mode", ["lifecycle", "native", "stalled", "killed", "memory_limit", "missing_reader"])
@pytest.mark.skipif(sys.platform != "linux", reason="The worker profiler uses Linux process supervision")
def test_memory_profiler_in_subprocess(mode: str) -> None:
    result = subprocess.run([sys.executable, "-c", WORKER, mode, NO_READER], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    logs = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"event":')]
    if mode == "lifecycle":
        assert any(
            log["event"] == "temporal_memray_allocations"
            and any(
                group["bytes"] >= 8 * 1024 * 1024
                and any(frame["function"] == "allocate_payload" for frame in group["stack"])
                for group in log["top_stacks"]
            )
            for log in logs
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"snapshot_interval_seconds": 0},
        {"log_interval_seconds": float("nan")},
        {"watchdog_timeout_seconds": 5},
        {"top_stacks": 101},
        {"collector_max_rss_mb": 0},
        {"metrics_port": 65536},
    ],
)
def test_invalid_profiler_configuration(overrides: dict) -> None:
    with pytest.raises(ValueError):
        replace(MemoryProfilerConfig(), **overrides)


@override_settings(TEMPORAL_MEMRAY_ENABLED=True)
def test_worker_continues_if_profiler_process_cannot_start() -> None:
    with patch("posthog.temporal.common.memory_profiler.subprocess.Popen", side_effect=OSError("process limit")):
        with pytest.raises(RuntimeError, match="worker error"):
            with profile_worker_memory("test-queue"):
                raise RuntimeError("worker error")
