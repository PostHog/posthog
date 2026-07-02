"""Bounded in-process buffer for the CSP report capture-forward.

The /report/ endpoint forwards every accepted report to capture-rs. Doing that
synchronously ties request-worker hold time to capture-rs latency (including its
retry budget), which starves bounded worker pools when capture-rs degrades. This
buffer decouples the two: the view enqueues and returns immediately, a background
sender thread batches events to ``capture_batch_internal``.

CSP reporting is best-effort by contract: on overflow the buffer drops the oldest
events (counted in ``csp_report_buffer_dropped``), and buffered events are lost if
the process dies before the final drain. Browsers never read report responses, so
callers get no delivery guarantee either way.
"""

from __future__ import annotations

import os
import queue
import atexit
import threading
from typing import Any

import structlog
from prometheus_client import Counter, Gauge

from posthog.api.capture import capture_batch_internal
from posthog.exceptions_capture import capture_exception
from posthog.settings.ingestion import (
    CSP_REPORT_BUFFER_FLUSH_INTERVAL_SECONDS,
    CSP_REPORT_BUFFER_FLUSH_MAX_EVENTS,
    CSP_REPORT_BUFFER_MAX_EVENTS,
)

logger = structlog.get_logger(__name__)

CSP_BUFFER_ENQUEUED = Counter(
    "csp_report_buffer_enqueued",
    "CSP report events accepted into the forward buffer.",
)
CSP_BUFFER_DROPPED = Counter(
    "csp_report_buffer_dropped",
    "CSP report events dropped from the forward buffer.",
    labelnames=["reason"],
)
CSP_BUFFER_SUBMITTED = Counter(
    "csp_report_buffer_submitted",
    "CSP report events successfully forwarded to capture.",
)
CSP_BUFFER_FAILED = Counter(
    "csp_report_buffer_failed",
    "CSP report events whose forward to capture failed.",
)
CSP_BUFFER_DEPTH = Gauge(
    "csp_report_buffer_depth",
    "Current number of events waiting in the forward buffer.",
)


class CspReportBuffer:
    def __init__(
        self,
        maxsize: int = CSP_REPORT_BUFFER_MAX_EVENTS,
        flush_interval: float = CSP_REPORT_BUFFER_FLUSH_INTERVAL_SECONDS,
        flush_max_events: int = CSP_REPORT_BUFFER_FLUSH_MAX_EVENTS,
    ) -> None:
        self.flush_interval = flush_interval
        self.flush_max_events = flush_max_events
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._sender: threading.Thread | None = None
        # Sender threads don't survive fork, so remember which process started ours.
        self._sender_pid: int | None = None
        # atexit doesn't deduplicate handlers, so register once per process even
        # if the sender thread gets restarted.
        self._atexit_pid: int | None = None

    def enqueue(self, events: list[dict[str, Any]], *, token: str) -> None:
        """Add events to the buffer without ever blocking the caller.

        On overflow the oldest queued events are evicted so fresh reports win.
        """
        self._ensure_sender()
        for event in events:
            while True:
                try:
                    self._queue.put_nowait((token, event))
                    break
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        CSP_BUFFER_DROPPED.labels(reason="overflow").inc()
                    except queue.Empty:
                        continue
        CSP_BUFFER_ENQUEUED.inc(len(events))
        CSP_BUFFER_DEPTH.set(self._queue.qsize())

    def _ensure_sender(self) -> None:
        if self._sender is not None and self._sender.is_alive() and self._sender_pid == os.getpid():
            return
        with self._lock:
            if self._sender is not None and self._sender.is_alive() and self._sender_pid == os.getpid():
                return
            self._sender_pid = os.getpid()
            self._sender = threading.Thread(target=self._run, name="csp-report-buffer-sender", daemon=True)
            self._sender.start()
            if self._atexit_pid != os.getpid():
                atexit.register(self._drain_on_exit)
                self._atexit_pid = os.getpid()

    def _run(self) -> None:
        while True:
            # A crashed sender would silently strand queued events until the next
            # enqueue restarts it — never let an exception escape the loop.
            try:
                batch = self._collect()
                if batch:
                    self._flush(batch)
            except Exception:
                logger.exception("csp_report_buffer_sender_error")

    def _collect(self) -> list[tuple[str, dict[str, Any]]]:
        """Wait up to ``flush_interval`` for work, then drain up to ``flush_max_events``."""
        items: list[tuple[str, dict[str, Any]]] = []
        try:
            items.append(self._queue.get(timeout=self.flush_interval))
        except queue.Empty:
            return items
        while len(items) < self.flush_max_events:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _flush(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        CSP_BUFFER_DEPTH.set(self._queue.qsize())
        by_token: dict[str, list[dict[str, Any]]] = {}
        for token, event in items:
            by_token.setdefault(token, []).append(event)
        for token, events in by_token.items():
            try:
                result = capture_batch_internal(
                    events=events,
                    token=token,
                    event_source="get_csp_report",
                    process_person_profile=False,
                )
                result.raise_for_status()
                CSP_BUFFER_SUBMITTED.inc(len(events))
            except Exception as exc:
                CSP_BUFFER_FAILED.inc(len(events))
                capture_exception(exc, {"capture-pathway": "csp_report_buffer", "ph-team-token": token})
                logger.warning("csp_report_buffer_flush_failed", batch_size=len(events), error=str(exc))

    def _drain_on_exit(self) -> None:
        # Best-effort final flush of at most one batch. The capture call itself can
        # still take its full timeout/retry budget — that has to fit inside the
        # pod's termination grace, it is not bounded here.
        items: list[tuple[str, dict[str, Any]]] = []
        while len(items) < self.flush_max_events:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if items:
            self._flush(items)


csp_report_buffer = CspReportBuffer()
