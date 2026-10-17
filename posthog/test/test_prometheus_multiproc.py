import os
import fcntl
import tempfile
import threading
from pathlib import Path

from unittest import TestCase
from unittest.mock import patch

from prometheus_client import multiprocess
from prometheus_client.mmap_dict import MmapedDict, mmap_key

from posthog.prometheus_multiproc import LockedMultiProcessCollector, PrometheusMultiprocDir


class TestPrometheusMultiprocDir(TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.multiproc = PrometheusMultiprocDir(str(self.directory))

    def _write(self, prefix: str, pid: int, samples: dict[str, tuple[float, float]]) -> Path:
        path = self.directory / f"{prefix}_{pid}.db"
        mmaped = MmapedDict(str(path))
        try:
            for key, (value, timestamp) in samples.items():
                mmaped.write_value(key, value, timestamp)
        finally:
            mmaped.close()
        return path

    def _all_samples(self) -> dict[str, float]:
        collector = multiprocess.MultiProcessCollector(None, path=str(self.directory))
        return {
            f"{sample.name}{sorted(sample.labels.items())}": sample.value
            for metric in collector.collect()
            for sample in metric.samples
        }

    def _scrape(self, name: str, labels: dict[str, str]) -> float | None:
        for metric in multiprocess.MultiProcessCollector(None, path=str(self.directory)).collect():
            for sample in metric.samples:
                if sample.name == name and sample.labels == labels:
                    return sample.value
        return None

    @staticmethod
    def _counter_key(task: str) -> str:
        return mmap_key("posthog_test", "posthog_test_total", ["task"], [task], "help")

    def test_the_scrape_keeps_a_retired_child_s_counter_total(self) -> None:
        # mark_process_dead keeps counter files because the scrape sums them. Deleting one
        # without archiving drops the total, which Prometheus reads as a counter reset.
        self._write("counter", 4242, {self._counter_key("a"): (7.0, 0.0)})
        self._write("counter", 4243, {self._counter_key("a"): (5.0, 0.0)})

        assert self.multiproc.retire_pids([4242]) == 1
        assert not (self.directory / "counter_4242.db").exists()
        assert self._scrape("posthog_test_total", {"task": "a"}) == 12.0

    def test_totals_survive_every_child_of_a_pod_being_retired(self) -> None:
        for pid in (4242, 4243, 4244):
            self._write("counter", pid, {self._counter_key("a"): (2.0, 0.0)})
            assert self.multiproc.retire_pids([pid]) == 1

        assert self._scrape("posthog_test_total", {"task": "a"}) == 6.0

    def test_a_histogram_scrapes_the_same_after_retirement(self) -> None:
        def bucket_key(le: str) -> str:
            return mmap_key("posthog_test", "posthog_test_bucket", ["le"], [le], "help")

        self._write("histogram", 4242, {bucket_key("1.0"): (3.0, 0.0), bucket_key("+Inf"): (4.0, 0.0)})
        before = self._all_samples()

        assert self.multiproc.retire_pids([4242]) == 1
        assert self._all_samples() == before

    def test_a_max_gauge_folds_by_max_not_by_sum(self) -> None:
        key = mmap_key("posthog_test_gauge", "posthog_test_gauge", [], [], "help")
        self._write("gauge_max", 4242, {key: (9.0, 0.0)})
        self._write("gauge_max", 4243, {key: (4.0, 0.0)})

        assert self.multiproc.retire_pids([4242, 4243]) == 2
        assert self._scrape("posthog_test_gauge", {}) == 9.0

    def test_a_mostrecent_gauge_folds_by_timestamp(self) -> None:
        key = mmap_key("posthog_test_gauge", "posthog_test_gauge", [], [], "help")
        self._write("gauge_mostrecent", 4242, {key: (9.0, 100.0)})
        self._write("gauge_mostrecent", 4243, {key: (4.0, 200.0)})

        assert self.multiproc.retire_pids([4242, 4243]) == 2
        assert self._scrape("posthog_test_gauge", {}) == 4.0

    def test_a_live_gauge_goes_with_its_process(self) -> None:
        # A live gauge reports what a running process is doing, so a dead process's value must
        # not outlive it in the archive.
        key = mmap_key("posthog_test_live", "posthog_test_live", [], [], "help")
        self._write("gauge_livemax", 4242, {key: (9.0, 0.0)})

        assert self.multiproc.retire_pids([4242]) == 1
        assert list(self.directory.glob("*.db")) == []

    def test_retire_leaves_a_pid_that_is_a_suffix_of_another(self) -> None:
        kept = self._write("counter", 1242, {self._counter_key("a"): (1.0, 0.0)})

        assert self.multiproc.retire_pids([242]) == 0
        assert kept.exists()

    def test_dead_processes_are_retired_and_live_ones_are_left_alone(self) -> None:
        dead = self._write("counter", 4242, {self._counter_key("a"): (1.0, 0.0)})
        live = self._write("counter", os.getpid(), {self._counter_key("b"): (1.0, 0.0)})

        with patch.object(PrometheusMultiprocDir, "_is_alive", staticmethod(lambda pid: pid == os.getpid())):
            assert self.multiproc.retire_dead_processes() == 1
        assert not dead.exists()
        assert live.exists()

    def test_a_pid_reused_while_cleanup_waits_keeps_its_files(self) -> None:
        # Liveness read before the lock can name a pid that a new child owns by the time the lock
        # arrives, and that child's file is live.
        kept = self._write("counter", 4242, {self._counter_key("a"): (1.0, 0.0)})
        alive: set[int] = set()
        holding = threading.Event()
        release = threading.Event()
        swept = threading.Event()
        checked = threading.Event()

        def is_alive(pid: int) -> bool:
            checked.set()
            return pid in alive

        def hold_the_lock() -> None:
            with self.multiproc._lock(fcntl.LOCK_EX):
                holding.set()
                release.wait(timeout=10)

        def sweep() -> None:
            self.multiproc.retire_dead_processes()
            swept.set()

        with patch.object(PrometheusMultiprocDir, "_is_alive", staticmethod(is_alive)):
            holder = threading.Thread(target=hold_the_lock)
            holder.start()
            assert holding.wait(timeout=10)
            sweeper = threading.Thread(target=sweep)
            sweeper.start()
            # The sweep must reach its liveness test only once it holds the lock, so nothing is
            # checked while it waits here. A new child takes the pid in the meantime.
            assert not checked.wait(timeout=0.3), "liveness was read before the lock"
            alive.add(4242)
            release.set()
            sweeper.join(timeout=10)
            holder.join(timeout=10)

        assert swept.is_set()
        assert kept.exists()

    def test_purge_all_clears_the_archive_too(self) -> None:
        # Boot cleanup must not carry a previous pod's totals into this one.
        self._write("counter", 4242, {self._counter_key("a"): (1.0, 0.0)})
        self.multiproc.retire_pids([4242])

        assert self.multiproc.purge_all() == 1
        assert list(self.directory.glob("*.db")) == []

    def test_an_unreadable_directory_does_not_break_child_startup(self) -> None:
        assert PrometheusMultiprocDir(str(self.directory / "gone")).retire_dead_processes() == 0

    def test_a_corrupt_file_is_still_reclaimed(self) -> None:
        # The archive is best effort: a file that cannot be read still has to free its space.
        corrupt = self.directory / "counter_4242.db"
        corrupt.write_bytes(b"\xff" * 64)

        assert self.multiproc.retire_pids([4242]) == 1
        assert not corrupt.exists()

    def test_the_collector_reads_the_files_samples(self) -> None:
        self._write("counter", 4242, {self._counter_key("a"): (7.0, 0.0)})

        collector = LockedMultiProcessCollector(self.multiproc)
        assert any(metric.samples for metric in collector.collect())

    def test_cleanup_waits_for_a_scrape_in_flight(self) -> None:
        # Drop the shared lock from collect() and prometheus_client raises FileNotFoundError for
        # a file deleted between its listing and its read, which fails the whole scrape.
        self._write("counter", 4242, {self._counter_key("a"): (7.0, 0.0)})
        collector = LockedMultiProcessCollector(self.multiproc)
        scraping = threading.Event()
        release = threading.Event()
        retired = threading.Event()

        def blocking_collect() -> list:
            scraping.set()
            release.wait(timeout=10)
            return []

        def retire() -> None:
            self.multiproc.retire_pids([4242])
            retired.set()

        with patch.object(collector, "_collector") as inner:
            inner.collect.side_effect = blocking_collect
            scraper = threading.Thread(target=collector.collect)
            scraper.start()
            try:
                assert scraping.wait(timeout=10)
                cleaner = threading.Thread(target=retire)
                cleaner.start()
                assert not retired.wait(timeout=0.3), "cleanup deleted a file under a live scrape"
            finally:
                release.set()
            cleaner.join(timeout=10)
            scraper.join(timeout=10)

        assert retired.is_set()
        assert not (self.directory / "counter_4242.db").exists()
