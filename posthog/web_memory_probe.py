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


def _open_libc() -> "ctypes.CDLL | None":
    """dlopen glibc once at import (dlopen is the costly part) and configure return types,
    so the handler doesn't re-resolve it on every probe. None on non-glibc platforms (dev
    macOS), where the probe degrades to RSS-only rather than erroring."""
    try:
        libc = ctypes.CDLL("libc.so.6")
    except OSError:
        return None
    try:
        libc.malloc_trim.restype = ctypes.c_int
        libc.malloc_trim.argtypes = (ctypes.c_size_t,)
    except AttributeError:
        pass
    try:
        libc.mallinfo2.restype = _Mallinfo2
    except AttributeError:
        # glibc < 2.33 lacks mallinfo2; the trim delta still works without the breakdown.
        pass
    return libc


_LIBC = _open_libc()


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
    if _LIBC is None:
        return None
    try:
        info = _LIBC.mallinfo2()
    except AttributeError:
        return None
    return {name: getattr(info, name) for name in _MALLINFO2_FIELDS}


def _handle_probe(signum: int, frame: FrameType | None) -> None:
    """SIGUSR2 handler — a one-shot memory diagnostic for a single worker. Python delivers
    signals on the main thread between bytecodes, so ordinary work (logging, ctypes calls)
    is safe here; logging's RLock is reentrant for the same thread, so interrupting a log
    call can't self-deadlock.

    Captures mallinfo2 *before* gc/trim disturb it (malloc_trim hands back exactly the
    reclaimable free-list pages, so a post-trim fordblks reads what's left, not what was
    hoarded), then RSS at three points plus malloc_trim's own return value. Read the verdict
    as — note gc.collect() frees cycles into glibc's free list, NOT back to the OS, so RSS
    may not move even when collection happened; key the cycle call off the count, not RSS:
      gc_collected large                 -> reference cycles are a factor (Python-level / gc tuning),
                                            independent of whether RSS moved
      (rss_before - rss_after_trim) large -> glibc was holding reclaimable pages (malloc_released == 1);
        or malloc_released == 1             jemalloc decay or a periodic trim would recover it -> the jemalloc gate
      both small                         -> memory is genuinely live (only fetching/retaining less helps)

    mallinfo2_before.fordblks vs uordblks is the free-list-vs-live split before trim runs.
    The gc.collect() costs a single pause on the one worker that's signalled, which is why
    this is fired by hand on a chosen pod, never on a schedule."""
    log = structlog.get_logger("posthog.web_memory_probe")
    mallinfo_before = _mallinfo2()
    rss_before = _read_vmrss_kb()
    gc_counts = gc.get_count()
    collected = gc.collect()
    rss_after_gc = _read_vmrss_kb()
    # malloc_trim(0) returns 1 if it actually released pages to the OS, 0 if not — a direct
    # answer that doesn't depend on a quiet-at-the-instant RSS sample (ctypes drops the GIL
    # during the call, so the sync threadpool can allocate and add noise to rss_after_trim).
    released: int | None = None
    if _LIBC is not None:
        try:
            released = int(_LIBC.malloc_trim(0))
        except (OSError, AttributeError):
            released = None
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
        malloc_released=released,
        mallinfo2_before=mallinfo_before,
        mallinfo2_after=_mallinfo2(),
    )


def install_memory_probe_handler() -> None:
    """Register the SIGUSR2 memory-probe handler, gated by WEB_MEMORY_PROBE_ENABLED.

    MUST be called post-fork from inside each worker (see posthog/asgi.py and posthog/wsgi.py):
    signal handlers can only be registered from the main thread, and the handler has to live
    in the worker that serves requests, not the idle Nginx Unit prototype the workers fork
    from. Registering post-fork also means it isn't clobbered by any signal reset Unit does
    during worker init.

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
