import pytest

from django.test import SimpleTestCase

from prometheus_client import REGISTRY

from posthog.session_recordings.session_recording_api import FETCH_BLOCKS_HISTOGRAM, _timed_snapshot_stage


def _count(labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value("session_snapshots_fetch_blocks_seconds_count", labels) or 0.0


class TestTimedSnapshotStage(SimpleTestCase):
    def test_observes_prom_and_propagates_exceptions(self) -> None:
        labels = {"decompress": "True"}
        before = _count(labels)

        # The stage must still be observed when the body raises, and the error must propagate.
        with pytest.raises(ValueError):
            with _timed_snapshot_stage(FETCH_BLOCKS_HISTOGRAM, labels):
                raise ValueError("boom")

        assert _count(labels) == before + 1
