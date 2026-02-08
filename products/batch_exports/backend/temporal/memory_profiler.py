"""Memory profiling utilities for batch exports.

This module provides tools to identify memory leaks and allocations
in batch export activities.
"""

import gc
import sys
import ctypes
import resource
import tracemalloc
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypedDict

import pyarrow as pa

from posthog.temporal.common.logger import get_write_only_logger

if TYPE_CHECKING:
    from collections.abc import Generator

LOGGER = get_write_only_logger(__name__)


class PyArrowPoolStats(TypedDict):
    bytes_allocated: int
    max_memory: int | None
    backend_name: str


class CleanupStats(TypedDict):
    rss_before_mb: float
    rss_after_mb: float
    rss_freed_mb: float
    pa_bytes_before: int
    pa_bytes_after: int
    pa_bytes_freed: int
    malloc_trimmed: bool


def get_rss_mb() -> float:
    """Get current RSS (Resident Set Size) in MB."""
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return rusage.ru_maxrss / 1024 / 1024
    return rusage.ru_maxrss / 1024


def get_pyarrow_pool_stats() -> PyArrowPoolStats:
    """Get PyArrow memory pool statistics."""
    pool = pa.default_memory_pool()
    return {
        "bytes_allocated": pool.bytes_allocated(),
        "max_memory": pool.max_memory(),
        "backend_name": pool.backend_name,
    }


def try_malloc_trim() -> bool:
    """Try to return freed memory to the OS using malloc_trim (Linux only).

    This can help when glibc's malloc has fragmented memory that it's
    holding onto but not using.
    """
    if sys.platform != "linux":
        return False

    try:
        libc = ctypes.CDLL("libc.so.6")
        result = libc.malloc_trim(0)
        return result == 1
    except (OSError, AttributeError):
        return False


def aggressive_cleanup() -> CleanupStats:
    """Perform aggressive memory cleanup and return stats.

    Returns:
        Dict with cleanup results including memory freed and actions taken.
    """
    rss_before = get_rss_mb()
    pa_before = get_pyarrow_pool_stats()

    # 1. Python garbage collection (multiple generations)
    gc.collect(0)
    gc.collect(1)
    gc.collect(2)

    # 2. PyArrow memory pool release
    pa.default_memory_pool().release_unused()

    # 3. Try to return memory to OS (Linux)
    malloc_trimmed = try_malloc_trim()

    rss_after = get_rss_mb()
    pa_after = get_pyarrow_pool_stats()

    return {
        "rss_before_mb": rss_before,
        "rss_after_mb": rss_after,
        "rss_freed_mb": rss_before - rss_after,
        "pa_bytes_before": pa_before["bytes_allocated"],
        "pa_bytes_after": pa_after["bytes_allocated"],
        "pa_bytes_freed": pa_before["bytes_allocated"] - pa_after["bytes_allocated"],
        "malloc_trimmed": malloc_trimmed,
    }


@contextmanager
def memory_profile_context(name: str, log_top_n: int = 10) -> "Generator[None, None, None]":
    """Context manager to profile memory allocations.

    Uses tracemalloc to identify where memory is being allocated.

    Args:
        name: Name for this profiling session (for logging).
        log_top_n: Number of top allocations to log.

    Example:
        with memory_profile_context("bigquery_export"):
            await run_export()
    """
    rss_before = get_rss_mb()
    pa_stats_before = get_pyarrow_pool_stats()

    # Start tracemalloc
    tracemalloc.start(10)  # Store 10 frames for tracebacks

    LOGGER.info(
        "Memory profile started",
        name=name,
        rss_mb=rss_before,
        pa_allocated_mb=pa_stats_before["bytes_allocated"] / 1024 / 1024,
    )

    try:
        yield
    finally:
        # Take snapshot and get stats
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        rss_after = get_rss_mb()
        pa_stats_after = get_pyarrow_pool_stats()

        # Get top allocations
        stats = snapshot.statistics("lineno")

        top_allocations = []
        for stat in stats[:log_top_n]:
            top_allocations.append(
                {
                    "file": str(stat.traceback),
                    "size_mb": stat.size / 1024 / 1024,
                    "count": stat.count,
                }
            )

        # Cleanup and measure again
        cleanup_stats = aggressive_cleanup()

        LOGGER.info(
            "Memory profile complete",
            name=name,
            rss_before_mb=rss_before,
            rss_after_mb=rss_after,
            rss_growth_mb=rss_after - rss_before,
            pa_before_mb=pa_stats_before["bytes_allocated"] / 1024 / 1024,
            pa_after_mb=pa_stats_after["bytes_allocated"] / 1024 / 1024,
            pa_peak_mb=pa_stats_after["max_memory"] / 1024 / 1024 if pa_stats_after["max_memory"] is not None else None,
            cleanup_rss_freed_mb=cleanup_stats["rss_freed_mb"],
            cleanup_pa_freed_mb=cleanup_stats["pa_bytes_freed"] / 1024 / 1024,
            top_allocations=top_allocations,
        )


def log_memory_status(label: str) -> None:
    """Log current memory status."""
    rss = get_rss_mb()
    pa_stats = get_pyarrow_pool_stats()
    gc_stats = gc.get_stats()

    LOGGER.info(
        "Memory status",
        label=label,
        rss_mb=rss,
        pa_allocated_mb=pa_stats["bytes_allocated"] / 1024 / 1024,
        pa_max_mb=pa_stats["max_memory"] / 1024 / 1024 if pa_stats["max_memory"] is not None else None,
        pa_backend=pa_stats["backend_name"],
        gc_gen0_collected=gc_stats[0].get("collected", 0) if gc_stats else 0,
        gc_gen1_collected=gc_stats[1].get("collected", 0) if len(gc_stats) > 1 else 0,
        gc_gen2_collected=gc_stats[2].get("collected", 0) if len(gc_stats) > 2 else 0,
    )
