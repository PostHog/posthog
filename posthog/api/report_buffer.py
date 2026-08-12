"""Bounded in-process buffer for the CSP report capture-forward.

The /report/ endpoint forwards every accepted report to capture-rs. Doing that
synchronously ties request-worker hold time to capture-rs latency (including its
retry budget), which starves bounded worker pools when capture-rs degrades. This
buffer decouples the two: the view enqueues and returns immediately, a background
sender thread batches events to ``capture_batch_internal``.

CSP reporting is best-effort by contract: oversized events and events beyond a
token's fair share of the buffer are dropped, on count or byte overflow the
oldest queued events are evicted, events still unsent when a flush exceeds its
wall-clock deadline are dropped, and buffered events are lost if the process
dies before the final drain (all drops counted in ``csp_report_buffer_dropped``).
Browsers never read report responses, so callers get no delivery guarantee
either way.
"""

from __future__ import annotations

import os
import json
import time
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
    CSP_REPORT_BUFFER_FLUSH_MAX_SECONDS,
    CSP_REPORT_BUFFER_MAX_BYTES,
    CSP_REPORT_BUFFER_MAX_EVENT_BYTES,
    CSP_REPORT_BUFFER_MAX_EVENTS,
    CSP_REPORT_BUFFER_MAX_TOKEN_SHARE,
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
    multiprocess_mode="livesum",
)


class CspReportBuffer:
    def __init__(
        self,
        maxsize: int = CSP_REPORT_BUFFER_MAX_EVENTS,
        flush_interval: float = CSP_REPORT_BUFFER_FLUSH_INTERVAL_SECONDS,
        flush_max_events: int = CSP_REPORT_BUFFER_FLUSH_MAX_EVENTS,
        flush_max_seconds: float = CSP_REPORT_BUFFER_FLUSH_MAX_SECONDS,
        max_token_share: float = CSP_REPORT_BUFFER_MAX_TOKEN_SHARE,
        max_bytes: int = CSP_REPORT_BUFFER_MAX_BYTES,
        max_event_bytes: int = CSP_REPORT_BUFFER_MAX_EVENT_BYTES,
    ) -> None:
        self.flush_interval = flush_interval
        self.flush_max_events = flush_max_events
        self.flush_max_seconds = flush_max_seconds
        self.max_bytes = max_bytes
        self.max_event_bytes = max_event_bytes
        # maxsize=0 makes queue.Queue unbounded, which silently removes the count
        # bound — the opposite of what zeroing the knob looks like it should do.
        maxsize = max(1, maxsize)
        self._queue: queue.Queue[tuple[str, dict[str, Any], int]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._sender: threading.Thread | None = None
        # Sender threads don't survive fork, so remember which process started ours.
        self._sender_pid: int | None = None
        # atexit doesn't deduplicate handlers, so register once per process even
        # if the sender thread gets restarted.
        self._atexit_pid: int | None = None
        # Fairness: no single token may occupy more than its share of the buffer,
        # so one team's report storm (or a bogus token — tokens are public and
        # only capture-rs truly validates them) cannot evict other tokens'
        # events on overflow.
        self._token_cap = max(1, int(maxsize * max_token_share))
        self._token_counts: dict[str, int] = {}
        # Byte accounting: the count cap alone doesn't bound memory, events carry
        # the raw report body. Guarded by _counts_lock like the token counts.
        self._total_bytes = 0
        self._counts_lock = threading.Lock()

    def enqueue(self, events: list[dict[str, Any]], *, token: str) -> None:
        """Add events to the buffer without ever blocking the caller.

        Oversized events and a token over its share drop the incoming event; on
        count or byte overflow the globally oldest events are evicted so fresh
        reports win across tokens.
        """
        self._ensure_sender()
        accepted = 0
        for event in events:
            # Serialized length bounds both the single event (request bodies can
            # be far larger than any legitimate CSP report) and, summed, the
            # buffer's total memory footprint.
            size = len(json.dumps(event, default=str))
            if size > self.max_event_bytes:
                CSP_BUFFER_DROPPED.labels(reason="oversized").inc()
                continue
            if not self._reserve_slot(token):
                CSP_BUFFER_DROPPED.labels(reason="token_share").inc()
                continue
            while True:
                try:
                    self._queue.put_nowait((token, event, size))
                    break
                except queue.Full:
                    self._evict_oldest("overflow")
            with self._counts_lock:
                self._total_bytes += size
            accepted += 1
            # _total_bytes is incremented after put and decremented after remove,
            # matched per item, so the unlocked read below is safe under the GIL:
            # it can only read a transiently stale total, never tear, and the count
            # self-corrects. Worst case is one over- or under-eviction, tolerable
            # for a best-effort buffer.
            while self._total_bytes > self.max_bytes:
                if not self._evict_oldest("bytes_overflow"):
                    break
        CSP_BUFFER_ENQUEUED.inc(accepted)
        CSP_BUFFER_DEPTH.set(self._queue.qsize())

    def _reserve_slot(self, token: str) -> bool:
        with self._counts_lock:
            if self._token_counts.get(token, 0) >= self._token_cap:
                return False
            self._token_counts[token] = self._token_counts.get(token, 0) + 1
            return True

    def _release_slot(self, token: str) -> None:
        with self._counts_lock:
            remaining = self._token_counts.get(token, 0) - 1
            if remaining > 0:
                self._token_counts[token] = remaining
            else:
                self._token_counts.pop(token, None)

    def _evict_oldest(self, reason: str) -> bool:
        try:
            token, _, size = self._queue.get_nowait()
        except queue.Empty:
            return False
        self._release_slot(token)
        with self._counts_lock:
            self._total_bytes -= size
        CSP_BUFFER_DROPPED.labels(reason=reason).inc()
        return True

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
                    try:
                        self._flush(batch)
                    finally:
                        self._release_bytes(batch)
            except Exception:
                logger.exception("csp_report_buffer_sender_error")

    def _collect(self) -> list[tuple[str, dict[str, Any], int]]:
        """Wait up to ``flush_interval`` for work, then drain up to ``flush_max_events``."""
        items: list[tuple[str, dict[str, Any], int]] = []
        try:
            items.append(self._queue.get(timeout=self.flush_interval))
        except queue.Empty:
            return items
        while len(items) < self.flush_max_events:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        for token, _, _ in items:
            self._release_slot(token)
        # Bytes stay reserved until the flush finishes (_release_bytes) — the
        # in-flight batch still holds the memory, so releasing here would let
        # the queue refill a full budget on top of it.
        return items

    def _release_bytes(self, items: list[tuple[str, dict[str, Any], int]]) -> None:
        with self._counts_lock:
            self._total_bytes -= sum(size for _, _, size in items)

    def _flush(self, items: list[tuple[str, dict[str, Any], int]]) -> None:
        CSP_BUFFER_DEPTH.set(self._queue.qsize())
        by_token: dict[str, list[dict[str, Any]]] = {}
        for token, event, _ in items:
            by_token.setdefault(token, []).append(event)
        # Token groups are submitted serially and tokens are attacker-controlled
        # (only capture-rs validates them), so a flood of distinct tokens against
        # a slow capture-rs would otherwise multiply the per-call transport
        # budget by up to flush_max_events groups — stalling the sender while
        # the queue evicts everything behind it. The deadline bounds the whole
        # flush; only the last group started before it can overshoot (by one
        # call's transport budget). Groups past the deadline are dropped and
        # counted, matching the buffer's best-effort contract.
        deadline = time.monotonic() + self.flush_max_seconds
        groups = list(by_token.items())
        for index, (token, events) in enumerate(groups):
            if time.monotonic() > deadline:
                remaining = sum(len(group_events) for _, group_events in groups[index:])
                CSP_BUFFER_DROPPED.labels(reason="flush_deadline").inc(remaining)
                logger.warning(
                    "csp_report_buffer_flush_deadline",
                    dropped=remaining,
                    groups_left=len(groups) - index,
                    flush_max_seconds=self.flush_max_seconds,
                )
                break
            try:
                # max_attempts=1: token groups are submitted serially, so a
                # degraded capture-rs must not multiply its timeout by resubmit
                # rounds across every group in the flush — drop and count
                # instead of stalling the sender for minutes.
                result = capture_batch_internal(
                    events=events,
                    token=token,
                    event_source="get_csp_report",
                    process_person_profile=False,
                    max_attempts=1,
                )
            except Exception as exc:
                CSP_BUFFER_FAILED.inc(len(events))
                capture_exception(exc, {"capture-pathway": "csp_report_buffer", "ph-team-token": token})
                logger.warning("csp_report_buffer_flush_failed", batch_size=len(events), error=str(exc))
                continue
            # Count per-event outcomes: a partial failure must not mark events
            # capture already accepted as lost — these counters are the only
            # delivery visibility in a fire-and-forget design, so
            # enqueued ≈ submitted + failed + dropped + depth has to hold.
            accepted = len(result.ok) + len(result.warnings)
            failed = len(result.dropped) + len(result.retried) + len(result.unaccounted)
            CSP_BUFFER_SUBMITTED.inc(accepted)
            if failed:
                CSP_BUFFER_FAILED.inc(failed)
                logger.warning(
                    "csp_report_buffer_flush_partial",
                    batch_size=len(events),
                    failed=failed,
                    error=result.error,
                )

    def _drain_on_exit(self) -> None:
        # Best-effort final flush of at most one batch, bounded by the same flush
        # deadline as regular flushes — flush_max_seconds (plus one call's
        # transport budget of overshoot) has to fit inside the pod's termination
        # grace.
        items: list[tuple[str, dict[str, Any], int]] = []
        while len(items) < self.flush_max_events:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        for token, _, _ in items:
            self._release_slot(token)
        if items:
            try:
                self._flush(items)
            finally:
                self._release_bytes(items)


csp_report_buffer = CspReportBuffer()
