import gc
import os
import ctypes
import signal
import logging
import threading
from types import FrameType

import structlog

PROBE_ENABLED_ENV = "WEB_MEMORY_PROBE_ENABLED"
_probe_lock = threading.Lock()

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
    fragmentation without walking the Python heap. None where libc/mallinfo2 is
    unavailable (non-glibc, e.g. dev macOS)."""
    if _LIBC is None:
        return None
    try:
        info = _LIBC.mallinfo2()
    except AttributeError:
        return None
    return {name: getattr(info, name) for name in _MALLINFO2_FIELDS}


def _handle_probe(signum: int, frame: FrameType | None) -> None:
    # A signal can interrupt an earlier probe, including its GC callbacks or logging.
    # Never wait here: the interrupted probe cannot release the lock until we return.
    if not _probe_lock.acquire(blocking=False):
        return
    try:
        _run_probe()
    except Exception:
        try:
            logging.getLogger(__name__).exception("web memory probe failed")
        except Exception:
            # Logging may itself be the failed diagnostic; don't unwind server code.
            pass
    finally:
        _probe_lock.release()


def _run_probe() -> None:
    """Run a synchronous diagnostic on the signalled worker's main thread.

    Capture mallinfo2 before GC and trim change the allocator's free lists. gc_collected
    counts unreachable objects, not bytes; collecting cycles need not reduce RSS.
    malloc_released reports whether glibc returned any pages, not how many.
    Collection skips the frozen startup heap. Concurrent request allocations can obscure
    RSS deltas, and glibc statistics do not describe a replacement allocator's heap.
    Small collection counts and RSS deltas therefore do not prove that all memory is live.
    GC and trim can pause requests, so fire this manually, never on a schedule."""
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

    MUST be called on each worker's main thread: WSGI installs during module import,
    before requests enter Granian's blocking thread pool; ASGI installs on the first request
    in the event loop. Granian's shutdown handlers leave SIGUSR2 untouched.

    Inert until armed: with the flag unset (default) nothing is registered at all, and even
    when armed the handler does nothing until a SIGUSR2 actually arrives. So the safe way to
    use it is to arm the flag fleet-wide and `kill -USR2 <worker_pid>` exactly one hot
    worker. Best-effort and idempotent — never breaks startup."""
    if os.getenv(PROBE_ENABLED_ENV, "").lower() not in ("1", "true", "yes"):
        return
    try:
        signal.signal(signal.SIGUSR2, _handle_probe)
        logging.getLogger(__name__).info("web memory probe handler installed on SIGUSR2")
    except (ValueError, OSError):
        # signal.signal raises ValueError off the main thread; stay best-effort.
        logging.getLogger(__name__).exception("failed to install web memory probe handler")
