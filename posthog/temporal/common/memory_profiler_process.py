import os
import sys
import json
import math
import time
import queue
import ctypes
import select
import signal
import socket
import threading
import subprocess
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from prometheus_client import CollectorRegistry, Gauge, generate_latest

if TYPE_CHECKING:
    from memray import AllocationRecord

MAX_MESSAGE_BYTES = 1024 * 1024


class AllocationFrame(TypedDict):
    function: str
    file: str
    line: int


class AllocationStack(TypedDict):
    bytes: int
    allocations: int
    stack: list[AllocationFrame]
    native_stack: NotRequired[list[AllocationFrame]]


class AllocationSnapshot(TypedDict):
    snapshot_timestamp_seconds: float
    outstanding_bytes: int
    outstanding_allocations: int
    stack_count: int
    stacks_omitted: int
    top_stacks: list[AllocationStack]
    stream_active: bool


class ProfilerSummary(AllocationSnapshot):
    schema_version: int
    worker_pid: int
    task_queue: str
    observed_peak_bytes: int
    stop_reason: str


# This module also runs as a standalone child; importing posthog.dataclasses would initialize Celery.
@dataclass(frozen=True, kw_only=True)
class MemoryProfilerConfig:
    metrics_host: str = "0.0.0.0"
    metrics_port: int = 8003
    native_traces: bool = False
    snapshot_interval_seconds: float = 5
    log_interval_seconds: float = 60
    top_stacks: int = 20
    startup_timeout_seconds: float = 15
    watchdog_timeout_seconds: float = 30
    collector_max_rss_mb: int = 256
    task_queue: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.metrics_port <= 65535:
            raise ValueError("Memray metrics port must be between 0 and 65535")
        if not 1 <= self.top_stacks <= 100 or self.collector_max_rss_mb <= 0:
            raise ValueError("Memray needs 1 to 100 top stacks and a positive collector RSS limit")
        for value in (
            self.snapshot_interval_seconds,
            self.log_interval_seconds,
            self.startup_timeout_seconds,
            self.watchdog_timeout_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Memray intervals and timeouts must be finite and positive")
        if self.watchdog_timeout_seconds <= self.snapshot_interval_seconds:
            raise ValueError("Memray watchdog timeout must exceed the snapshot interval")


def kill_with_parent(parent_pid: int) -> None:
    # A dead supervisor must close the reader socket even if the collector has lost its GIL.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not set profiler parent-death signal")
    if os.getppid() != parent_pid:
        os._exit(1)


def allocation_summary(
    records: list["AllocationRecord"], top_stacks: int, *, native_traces: bool = False
) -> AllocationSnapshot:
    groups: list[AllocationStack] = []
    for record in sorted(records, key=lambda record: record.size, reverse=True)[:top_stacks]:
        groups.append(
            {
                "bytes": record.size,
                "allocations": record.n_allocations,
                "stack": [
                    {"function": function[:240], "file": filename[:240], "line": line}
                    for function, filename, line in record.stack_trace(max_stacks=16)
                ],
            }
        )
        if native_traces:
            groups[-1]["native_stack"] = [
                {"function": function[:240], "file": filename[:240], "line": line}
                for function, filename, line in record.native_stack_trace(max_stacks=16)
            ]
    return {
        "snapshot_timestamp_seconds": time.time(),
        "outstanding_bytes": sum(record.size for record in records),
        "outstanding_allocations": sum(record.n_allocations for record in records),
        "stack_count": len(records),
        "stacks_omitted": max(0, len(records) - top_stacks),
        "top_stacks": groups,
        "stream_active": True,
    }


def collect(config: MemoryProfilerConfig, channel: socket.socket, stream_port: int) -> None:
    import memray  # noqa: PLC0415 - only the collector needs the native reader

    with memray.SocketReader(stream_port) as reader:
        while reader.is_active:
            summary = allocation_summary(
                list(reader.get_current_snapshot(merge_threads=True)),
                config.top_stacks,
                native_traces=config.native_traces,
            )
            summary["stream_active"] = reader.is_active
            message = json.dumps(summary, allow_nan=False).encode() + b"\n"
            if len(message) > MAX_MESSAGE_BYTES:
                raise ValueError("Memray summary exceeds IPC limit")
            channel.sendall(message)
            if select.select([channel], [], [], config.snapshot_interval_seconds)[0]:
                return


class ProfilerOutput:
    def __init__(self, config: MemoryProfilerConfig, worker_pid: int) -> None:
        self.config = config
        self.registry = CollectorRegistry()
        self.gauges = {
            key: Gauge(name, description, registry=self.registry)
            for key, name, description in (
                (
                    "outstanding_bytes",
                    "memray_tracked_outstanding_bytes",
                    "Outstanding bytes allocated since profiling started.",
                ),
                (
                    "outstanding_allocations",
                    "memray_tracked_outstanding_allocations",
                    "Outstanding tracked allocations.",
                ),
                ("observed_peak_bytes", "memray_observed_peak_bytes", "Largest sampled outstanding byte count."),
                ("stream_active", "memray_stream_active", "Whether the allocation stream is connected."),
                (
                    "snapshot_timestamp_seconds",
                    "memray_snapshot_timestamp_seconds",
                    "Unix time of the latest allocation snapshot.",
                ),
            )
        }
        self.summary: ProfilerSummary = {
            "schema_version": 1,
            "worker_pid": worker_pid,
            "task_queue": config.task_queue,
            "stream_active": False,
            "snapshot_timestamp_seconds": 0,
            "outstanding_bytes": 0,
            "outstanding_allocations": 0,
            "observed_peak_bytes": 0,
            "top_stacks": [],
            "stack_count": 0,
            "stacks_omitted": 0,
            "stop_reason": "starting",
        }
        self.lock = threading.Lock()
        self.json_body = b"{}"
        self.metrics_body = b""
        self.logs: queue.Queue[str] = queue.Queue(maxsize=1)
        self.next_log = 0.0
        threading.Thread(target=self._write_logs, daemon=True).start()
        self.update(None, reason="starting")

    def _write_logs(self) -> None:
        while True:
            sys.stdout.write(self.logs.get() + "\n")
            sys.stdout.flush()

    def update(self, snapshot: AllocationSnapshot | None, *, reason: str = "") -> None:
        if snapshot is not None:
            self.summary.update(snapshot)
        self.summary["stop_reason"] = reason
        if reason:
            self.summary["stream_active"] = False
        self.summary["observed_peak_bytes"] = max(
            self.summary["observed_peak_bytes"], self.summary["outstanding_bytes"]
        )
        self.gauges["outstanding_bytes"].set(self.summary["outstanding_bytes"])
        self.gauges["outstanding_allocations"].set(self.summary["outstanding_allocations"])
        self.gauges["observed_peak_bytes"].set(self.summary["observed_peak_bytes"])
        self.gauges["stream_active"].set(self.summary["stream_active"])
        self.gauges["snapshot_timestamp_seconds"].set(self.summary["snapshot_timestamp_seconds"])
        with self.lock:
            self.json_body = json.dumps(self.summary, allow_nan=False).encode()
            self.metrics_body = generate_latest(self.registry)
        now = time.monotonic()
        if reason or now >= self.next_log:
            event = "temporal_memray_status" if reason else "temporal_memray_allocations"
            try:
                self.logs.put_nowait(json.dumps({"event": event, **self.summary}, allow_nan=False))
            except queue.Full:
                if reason:
                    try:
                        self.logs.get_nowait()
                    except queue.Empty:
                        pass
                    self.logs.put_nowait(json.dumps({"event": event, **self.summary}, allow_nan=False))
            self.next_log = now + self.config.log_interval_seconds

    def server(self) -> ThreadingHTTPServer:
        output = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/metrics":
                    with output.lock:
                        body, content_type = output.metrics_body, "text/plain; version=0.0.4"
                elif self.path == "/memory/allocations" and self.client_address[0] == "127.0.0.1":
                    with output.lock:
                        body, content_type = output.json_body, "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer((self.config.metrics_host, self.config.metrics_port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def collector_rss_bytes(pid: int) -> int:
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def stream_has_backlog(port: int) -> bool:
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if int(fields[1].split(":")[1], 16) == port and fields[3] == "01":
            if int(fields[4].split(":")[0], 16) > 0:
                return True
    return False


def supervise(config: MemoryProfilerConfig, control: socket.socket, worker_pid: int) -> None:
    output = ProfilerOutput(config, worker_pid)
    server = output.server()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        stream_port = reservation.getsockname()[1]
    incoming, outgoing = socket.socketpair()
    child = subprocess.Popen(
        [
            sys.executable,
            __file__,
            "collect",
            json.dumps(asdict(config)),
            str(outgoing.fileno()),
            str(stream_port),
            str(os.getpid()),
        ],
        pass_fds=(outgoing.fileno(),),
        stdin=subprocess.DEVNULL,
        # Native symbol lookup must not download debug archives or wait on an external service.
        env={**os.environ, "DEBUGINFOD_URLS": ""},
    )
    outgoing.close()
    try:
        control.sendall(
            json.dumps(
                {"stream_port": stream_port, "metrics_port": server.server_port, "collector_pid": child.pid}
            ).encode()
            + b"\n"
        )
        incoming.setblocking(False)
        pending = b""
        deadline = time.monotonic() + config.startup_timeout_seconds
        backlog_since: float | None = None
        stopped = False
        while os.getppid() == worker_pid:
            readable, _, _ = select.select([control] if stopped else [control, incoming], [], [], 0.25)
            if control in readable:
                break
            if stopped:
                continue
            now = time.monotonic()
            reason = ""
            if incoming in readable:
                chunk = incoming.recv(65536)
                if not chunk:
                    reason = "collector_exited"
                pending += chunk
                while b"\n" in pending:
                    message, pending = pending.split(b"\n", 1)
                    snapshot = cast(AllocationSnapshot, json.loads(message))
                    output.update(snapshot)
                    deadline = now + config.watchdog_timeout_seconds
                    if not snapshot["stream_active"]:
                        reason = "stream_closed"
                if len(pending) > MAX_MESSAGE_BYTES:
                    reason = "summary_too_large"
            if child.poll() is not None:
                reason = "collector_exited"
            elif now >= deadline:
                reason = "collector_timeout"
            elif collector_rss_bytes(child.pid) > config.collector_max_rss_mb * 1024 * 1024:
                reason = "collector_memory_limit"
            # A reader thread can stall while its snapshot thread still responds.
            if stream_has_backlog(stream_port):
                backlog_since = backlog_since if backlog_since is not None else now
                if now - backlog_since >= config.watchdog_timeout_seconds:
                    reason = "stream_backpressure"
            else:
                backlog_since = None
            if reason:
                child.kill()
                child.wait(timeout=5)
                output.update(None, reason=reason)
                stopped = True
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        incoming.close()
        server.shutdown()
        server.server_close()


def main() -> None:
    mode, raw_config, raw_fd, raw_target, raw_parent = sys.argv[1:]
    config = MemoryProfilerConfig(**json.loads(raw_config))
    parent_pid = int(raw_parent)
    if mode == "collect":
        kill_with_parent(parent_pid)
    with socket.socket(fileno=int(raw_fd)) as channel:
        if mode == "collect":
            collect(config, channel, int(raw_target))
        else:
            supervise(config, channel, parent_pid)


if __name__ == "__main__":
    main()
