"""Housekeeping for the file-backed prometheus metrics that prefork children write.

prometheus_client's multiprocess mode gives every process its own ``<prefix>_<pid>.db`` file and
merges the files at scrape time. Nothing in the library removes the files of a process that ends:
``multiprocess.mark_process_dead`` drops the live gauge files only. A celery worker recycles its
children constantly (``--max-tasks-per-child``), so the leftovers fill the volume and every later
metric on that pod fails with ENOSPC.

A dead process's samples are folded into a per-prefix archive file before its own files go, so the
scrape keeps the totals while the number of files stops growing with the number of children.
"""

import os
import fcntl
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from enum import Enum

import structlog
from prometheus_client import multiprocess
from prometheus_client.metrics_core import Metric
from prometheus_client.mmap_dict import MmapedDict
from prometheus_client.registry import Collector

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)


class MergeMode(Enum):
    """How the samples of two processes combine, mirroring the scrape's own arithmetic."""

    SUM = "sum"
    MIN = "min"
    MAX = "max"
    MOST_RECENT = "mostrecent"


@frozen
class Sample:
    """One reading of one metric, as prometheus_client holds it in a file."""

    value: float
    timestamp: float

    @classmethod
    def from_pair(cls, pair: tuple[float, float]) -> "Sample":
        """Adopt the pair that the mmap layer returns, which is the only place they arrive in."""
        value, timestamp = pair
        return cls(value=value, timestamp=timestamp)


@frozen
class MetricFile:
    """One ``<prefix>_<owner>.db`` file, where the prefix types it and the owner wrote it."""

    prefix: str
    owner: str
    path: str

    @property
    def pid(self) -> int | None:
        """The process that wrote the file, or None for the archive that outlives them."""
        try:
            return int(self.owner)
        except ValueError:
            return None


class PrometheusMultiprocDir:
    """The directory the prefork children write their metric files to."""

    _SUFFIX = ".db"
    _ARCHIVE_OWNER = "archive"
    _LOCK_NAME = "housekeeping.lock"

    # Which file prefixes outlive the process that wrote them, and how their samples combine.
    # A live gauge is dropped with its process by contract, and an "all" gauge carries the pid as
    # a label, so neither is archived.
    _MERGE_MODES = {
        "counter": MergeMode.SUM,
        "histogram": MergeMode.SUM,
        "summary": MergeMode.SUM,
        "gauge_sum": MergeMode.SUM,
        "gauge_min": MergeMode.MIN,
        "gauge_max": MergeMode.MAX,
        "gauge_mostrecent": MergeMode.MOST_RECENT,
    }

    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def from_environment(cls) -> "PrometheusMultiprocDir | None":
        """Build the directory prometheus_client was told to use, or None when it was not."""
        path = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if not path:
            return None
        os.makedirs(path, exist_ok=True)
        return cls(path)

    @classmethod
    def _describe(cls, entry: os.DirEntry) -> MetricFile | None:
        """Read ``counter_17.db`` as the prefix that types it and the owner that wrote it."""
        if not entry.name.endswith(cls._SUFFIX):
            return None
        prefix, _, owner = entry.name[: -len(cls._SUFFIX)].rpartition("_")
        if not prefix or not owner:
            return None
        return MetricFile(prefix=prefix, owner=owner, path=entry.path)

    @staticmethod
    def _is_alive(pid: int) -> bool:
        # Only ProcessLookupError means the process is gone. Any other answer keeps the files,
        # because a file we cannot judge is cheaper than a file we take from a live writer.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    @staticmethod
    def _combine(mode: MergeMode, old: Sample, new: Sample) -> Sample:
        if mode is MergeMode.SUM:
            return Sample(value=old.value + new.value, timestamp=0.0)
        if mode is MergeMode.MIN:
            return old if old.value <= new.value else new
        if mode is MergeMode.MAX:
            return old if old.value >= new.value else new
        return old if old.timestamp >= new.timestamp else new

    @contextmanager
    def _lock(self, operation: int) -> Iterator[None]:
        """Hold the housekeeping lock, which the scrape shares and the cleanup takes alone.

        The kernel releases a flock when its holder dies, so a killed child cannot wedge the
        children that replace it. A lock we cannot take is not worth a leaked disk, so the caller
        continues either way.
        """
        try:
            handle = open(os.path.join(self.path, self._LOCK_NAME), "a+b")
        except OSError as e:
            logger.warning("prometheus_multiproc_lock_open_failed", directory=self.path, error=str(e))
            yield
            return
        try:
            try:
                fcntl.flock(handle, operation)
            except OSError as e:
                logger.warning("prometheus_multiproc_lock_failed", directory=self.path, error=str(e))
            yield
        finally:
            handle.close()

    @contextmanager
    def shared_lock(self) -> Iterator[None]:
        """Keep the files still for the length of a scrape."""
        with self._lock(fcntl.LOCK_SH):
            yield

    def _entries(self) -> list[os.DirEntry]:
        try:
            return [entry for entry in os.scandir(self.path) if entry.is_file(follow_symlinks=False)]
        except OSError as e:
            logger.warning("prometheus_multiproc_scan_failed", directory=self.path, error=str(e))
            return []

    def _metric_files(self) -> list[MetricFile]:
        described = (self._describe(entry) for entry in self._entries())
        return [metric_file for metric_file in described if metric_file is not None]

    def _unlink(self, path: str) -> bool:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return False
        except OSError as e:
            logger.warning("prometheus_multiproc_remove_failed", file=path, error=str(e))
            return False
        return True

    def _archive(self, metric_file: MetricFile) -> None:
        """Fold one file's samples into the archive that outlives the process."""
        mode = self._MERGE_MODES.get(metric_file.prefix)
        if mode is None:
            return
        archive_name = f"{metric_file.prefix}_{self._ARCHIVE_OWNER}{self._SUFFIX}"
        archive = None
        try:
            readings = list(MmapedDict.read_all_values_from_file(metric_file.path))
            if not readings:
                return
            archive = MmapedDict(os.path.join(self.path, archive_name))
            known = {key for key, _, _ in archive.read_all_values()}
            for key, value, timestamp, _ in readings:
                sample = Sample(value=value, timestamp=timestamp)
                if key in known:
                    sample = self._combine(mode, Sample.from_pair(archive.read_value(key)), sample)
                archive.write_value(key, sample.value, sample.timestamp)
                known.add(key)
        except Exception as e:
            # Reclaiming the disk matters more than the samples on it: the caller deletes the file
            # either way, and a full volume is exactly when the archive write fails.
            logger.warning("prometheus_multiproc_archive_failed", file=metric_file.path, error=str(e))
        finally:
            if archive is not None:
                archive.close()

    def _retire(self, should_retire: Callable[[MetricFile], bool]) -> int:
        """Archive and delete the files the caller picks. The exclusive lock must be held."""
        retired = 0
        for metric_file in self._metric_files():
            if not should_retire(metric_file):
                continue
            self._archive(metric_file)
            if self._unlink(metric_file.path):
                retired += 1
        return retired

    def retire_pids(self, pids: Iterable[int]) -> int:
        """Archive the samples of the given processes, then delete the files they own."""
        owners = {str(pid) for pid in pids}
        if not owners:
            return 0
        with self._lock(fcntl.LOCK_EX):
            return self._retire(lambda metric_file: metric_file.owner in owners)

    def retire_dead_processes(self) -> int:
        """Retire the files of processes that are gone, so a full pod recovers without a restart.

        A child that is killed (OOM, SIGKILL) never runs its shutdown handler. The liveness test
        runs under the lock and picks the files themselves, because a pid read before the lock can
        belong to a new child by the time the lock arrives, and that child's file is live.
        """
        with self._lock(fcntl.LOCK_EX):
            return self._retire(lambda metric_file: metric_file.pid is not None and not self._is_alive(metric_file.pid))

    def purge_all(self) -> int:
        """Delete every metric file, archives included. Only safe before the children write."""
        removed = 0
        with self._lock(fcntl.LOCK_EX):
            for entry in self._entries():
                if entry.name.endswith(self._SUFFIX) and self._unlink(entry.path):
                    removed += 1
        return removed


class LockedMultiProcessCollector(Collector):
    """Read the metric files with the housekeeping lock held.

    Without the lock a scrape can list a file and then find it deleted, and prometheus_client
    re-raises that for every prefix except the live gauges, which fails the whole scrape.
    """

    def __init__(self, directory: PrometheusMultiprocDir) -> None:
        self._directory = directory
        self._collector = multiprocess.MultiProcessCollector(None, path=directory.path)

    def collect(self) -> Iterable[Metric]:
        with self._directory.shared_lock():
            return self._collector.collect()
