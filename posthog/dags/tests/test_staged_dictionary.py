from typing import Any, cast

import pytest

import dagster
from parameterized import parameterized

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common.staged_dictionary import (
    StageableDictionary,
    StagedDictionary,
    load_and_verify_on_every_cluster,
)


class _Checksums:
    def __init__(self, by_host: dict[str, int]) -> None:
        self._by_host = by_host

    def result(self) -> dict[str, int]:
        return self._by_host


class _StubCluster:
    """Enough of a handle for the verification gate: a name, and a checksum per host."""

    def __init__(self, name: str, checksums: dict[str, int]) -> None:
        self.data_cluster_name = name
        self._checksums = checksums

    def map_all_hosts(self, fn: Any, concurrency: int | None = None) -> _Checksums:
        return _Checksums(self._checksums)


class _StubDictionary:
    name = "snapshot_dictionary"
    query = "SELECT 1"

    def staged(self) -> StagedDictionary:
        raise NotImplementedError

    def load(self, client: Any) -> int:
        raise NotImplementedError


def _verify(clusters: list[_StubCluster]) -> None:
    load_and_verify_on_every_cluster(
        cast(list[ClickhouseCluster], clusters), cast(StageableDictionary, _StubDictionary())
    )


class TestLoadAndVerifyOnEveryCluster:
    @parameterized.expand(
        [
            ("one cluster disagrees with the other", {"a": 1}, {"b": 2}),
            ("two hosts of one cluster disagree", {"a": 1, "b": 2}, {"c": 1}),
        ]
    )
    def test_it_fails_when_the_rows_are_not_identical_everywhere(
        self, _name: str, first: dict[str, int], second: dict[str, int]
    ) -> None:
        # This gate is the only thing standing between a stale staged object and a mutation that
        # joins an empty dictionary, changes nothing, and reports success.
        with pytest.raises(dagster.Failure, match="does not hold the same rows"):
            _verify([_StubCluster("posthog", first), _StubCluster("events", second)])

    def test_it_passes_when_every_host_agrees(self) -> None:
        _verify([_StubCluster("posthog", {"a": 7, "b": 7}), _StubCluster("events", {"c": 7})])

    def test_it_names_both_clusters_when_they_disagree(self) -> None:
        # The message is the only clue to which side went stale, so a run that fails here is
        # actionable rather than a bare assertion.
        with pytest.raises(dagster.Failure) as failure:
            _verify([_StubCluster("posthog", {"a": 1}), _StubCluster("events", {"b": 2})])

        assert "posthog=[1]" in str(failure.value.description)
        assert "events=[2]" in str(failure.value.description)
