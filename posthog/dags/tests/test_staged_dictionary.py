from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common.staged_dictionary import (
    StageableDictionary,
    StagedDictionary,
    create_on_every_cluster,
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


class _Done:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def result(self) -> Any:
        return self._value


class _RecordingCluster:
    """A handle whose single host is a client named after the cluster, so calls say where they ran."""

    def __init__(self, name: str) -> None:
        self.data_cluster_name = name

    def map_all_hosts(self, fn: Any, concurrency: int | None = None) -> _Done:
        return _Done({self.data_cluster_name: fn(self.data_cluster_name)})

    def any_host_by_role(self, fn: Any, role: Any) -> _Done:
        return _Done(fn(self.data_cluster_name))


_STAGED = StagedDictionary(key="snapshot_dictionary.parquet", columns="id", structure="id Int64")


class _RecordingDictionary:
    name = "snapshot_dictionary"
    query = "SELECT FROM source"

    def __init__(self, left_behind: dict[str, str]) -> None:
        self.source_by_cluster = dict(left_behind)

    def staged(self) -> StagedDictionary:
        return _STAGED

    def create(self, client: Any, shards: int, max_execution_time: int, max_memory_usage: int, query: Any = None):
        self.source_by_cluster.setdefault(client, query or self.query)

    def recreate(self, client: Any, shards: int, max_execution_time: int, max_memory_usage: int, query: Any = None):
        self.source_by_cluster.pop(client, None)
        self.create(client, shards, max_execution_time, max_memory_usage, query)


class TestCreateOnEveryCluster:
    @parameterized.expand(
        [
            ("one cluster reads the source table", ["posthog"], False, False),
            ("every cluster reads the staged object, the source cluster too", ["posthog", "events"], True, False),
            ("one cluster replaces a staged definition a failed run left", ["posthog"], False, True),
        ]
    )
    def test_the_dictionary_source_on_each_cluster(
        self, _name: str, names: list[str], staged: bool, left_behind: bool
    ) -> None:
        # A source cluster that reads the live table sees rows written after the export while its
        # hosts load one by one, so its hosts disagree with each other and with the other cluster.
        # A kept staged definition loads a stale object, so the run deletes an old key set.
        dictionary = _RecordingDictionary({"posthog": _STAGED.query} if left_behind else {})
        expected = dictionary.staged().query if staged else dictionary.query

        with patch.object(StagedDictionary, "export"):
            create_on_every_cluster(
                MagicMock(),
                cast(list[ClickhouseCluster], [_RecordingCluster(name) for name in names]),
                cast(StageableDictionary, dictionary),
                shards=1,
                max_execution_time=0,
                max_memory_usage=0,
            )

        assert dictionary.source_by_cluster == dict.fromkeys(names, expected)
