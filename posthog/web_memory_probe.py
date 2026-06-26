import gc
import os
import ctypes
import signal
import logging
from types import FrameType

import structlog

logger = logging.getLogger(__name__)

PROBE_ENABLED_ENV = "WEB_MEMORY_PROBE_ENABLED"

# glibc mallinfo2() layout — all size_t (see `man mallinfo2`). mallinfo2 (glibc >= 2.33)
# supersedes mallinfo(), whose int fields overflow on the multi-GB heaps we care about.
# fordblks (free, reclaimable) vs uordblks (in use) vs hblkhd (mmapped) is the breakdown
# that tells us how much glibc is sitting on without returning to the OS.
_MALLINFO2_FIELDS = (
    "arena",
    "ordblks",
    "smblks",
    "hblks",
    "hblkhd",
    "usmblks",
    "fsmblks",
    "uordblks",
    "fordblks",
    "keepcost",
)


class _Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in _MALLINFO2_FIELDS]


def _read_vmrss_kb() -> int | None:
    """Resident set size of this process in kB, from /proc/self/status. A process can
    always read its own status — no CAP_SYS_PTRACE needed, unlike /proc/<pid>/smaps or
    attaching a profiler. Returns None off Linux (dev machines without /proc)."""
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _mallinfo2() -> dict[str, int] | None:
    """glibc allocator stats: how much the process has taken from the OS and how much is
    parked on free lists (fordblks) rather than returned. Quantifies reclaimable
    fragmentation directly, in O(1), without a heap walk. None where libc/mallinfo2 is
    unavailable (non-glibc, e.g. dev macOS)."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.mallinfo2.restype = _Mallinfo2
        info = libc.mallinfo2()
    except (OSError, AttributeError):
        return None
    return {name: getattr(info, name) for name in _MALLINFO2_FIELDS}


def _handle_probe(signum: int, frame: FrameType | None) -> None:
    """SIGUSR2 handler — a one-shot memory diagnostic for a single worker. Python delivers
    signals on the main thread between bytecodes, so ordinary work (logging, ctypes calls)
    is safe here; logging's RLock is reentrant for the same thread, so interrupting a log
    call can't self-deadlock.

    Reads RSS at three points — as-is, after gc.collect(), after malloc_trim(0) — which is
    enough to tell apart the three causes of a high resident set without a GIL-blocking
    heap walk:
      after_gc  << before    -> uncollected reference cycles were holding memory (Python-level)
      after_trim << after_gc -> glibc was sitting on reclaimable freed pages (jemalloc / a trim cron would recover it)
      all three ~ equal      -> memory is live and referenced (only fetching/retaining less helps)

    The gc.collect() costs a single pause on the one worker that's signalled, which is why
    this is fired by hand on a chosen pod, never on a schedule."""
    log = structlog.get_logger("posthog.web_memory_probe")
    rss_before = _read_vmrss_kb()
    gc_counts = gc.get_count()
    collected = gc.collect()
    rss_after_gc = _read_vmrss_kb()
    trimmed = False
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
        trimmed = True
    except (OSError, AttributeError):
        pass
    rss_after_trim = _read_vmrss_kb()
    log.warning(
        "web_memory_probe",
        pid=os.getpid(),
        pod=os.getenv("K8S_POD_NAME") or os.getenv("HOSTNAME"),
        rss_kb_before=rss_before,
        rss_kb_after_gc=rss_after_gc,
        rss_kb_after_trim=rss_after_trim,
        gc_collected=collected,
        gc_uncollectable=len(gc.garbage),
        gc_counts=gc_counts,
        malloc_trimmed=trimmed,
        mallinfo2=_mallinfo2(),
    )


def install_memory_probe_handler() -> None:
    """Register the SIGUSR2 memory-probe handler, gated by WEB_MEMORY_PROBE_ENABLED.

    MUST be called post-fork from inside each worker (see posthog/asgi.py): signal handlers
    can only be registered from the main thread, and the handler has to live in the worker
    that serves requests, not the idle Nginx Unit prototype the workers fork from.

    Inert until armed: with the flag unset (default) nothing is registered at all, and even
    when armed the handler does nothing until a SIGUSR2 actually arrives. So the safe way to
    use it is to arm the flag fleet-wide and `kill -USR2 <worker_pid>` exactly one hot
    worker. Best-effort and idempotent — never breaks startup."""
    if os.getenv(PROBE_ENABLED_ENV, "").lower() not in ("1", "true", "yes"):
        return
    try:
        signal.signal(signal.SIGUSR2, _handle_probe)
        logger.info("web memory probe handler installed on SIGUSR2")
    except (ValueError, OSError):
        # signal.signal raises ValueError off the main thread; stay best-effort.
        logger.exception("failed to install web memory probe handler")
