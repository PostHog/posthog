from datetime import UTC, datetime

import pytest

from parameterized import parameterized

from posthog.local_bootstrap.config import BootstrapConfig, BootstrapConfigError, S3Location, TableImportConfig
from posthog.local_bootstrap.importer import ZERO_UUID, Progress, _accumulate_persons, _event_row_to_ch
from posthog.local_bootstrap.source import _matches_format


def _events_config() -> TableImportConfig:
    return TableImportConfig(
        table="events", location=S3Location(bucket="dump"), file_format="Parquet", compression="zstd"
    )


class TestConfigValidation:
    @parameterized.expand(
        [
            ("bad_format", "Avro", "zstd"),
            ("bad_parquet_compression", "Parquet", "snappy_typo"),
            ("jsonl_rejects_zstd", "JSONLines", "zstd"),  # zstd is parquet-only, like the export feature
        ]
    )
    def test_rejects_unsupported_format_or_compression(self, _name, file_format, compression):
        config = TableImportConfig(
            table="events", location=S3Location(bucket="dump"), file_format=file_format, compression=compression
        )
        with pytest.raises(BootstrapConfigError):
            config.validate()

    def test_rejects_missing_bucket(self):
        with pytest.raises(BootstrapConfigError):
            TableImportConfig(table="events", location=S3Location(bucket="")).validate()

    def test_accepts_parquet_zstd_and_no_compression(self):
        TableImportConfig(
            table="events", location=S3Location(bucket="d"), file_format="Parquet", compression="zstd"
        ).validate()
        TableImportConfig(
            table="persons", location=S3Location(bucket="d"), file_format="JSONLines", compression=None
        ).validate()

    def test_bootstrap_config_requires_at_least_one_table(self):
        with pytest.raises(BootstrapConfigError):
            BootstrapConfig(project_name="p", email="a@b.com", tables=[]).validate()


class TestMatchesFormat:
    @parameterized.expand(
        [
            ("plain_parquet", "exp/2024-01-01-2024-01-02.parquet", "Parquet", True),
            ("zstd_parquet", "exp/2024-01-01-2024-01-02-0.parquet.zst", "Parquet", True),
            ("gzip_parquet", "exp/chunk.parquet.gz", "Parquet", True),
            ("manifest_excluded", "exp/2024-01-01-2024-01-02_manifest.json", "Parquet", False),
            ("directory_excluded", "exp/", "Parquet", False),
            ("wrong_format", "exp/chunk.jsonl", "Parquet", False),
            ("jsonl_gzip", "exp/chunk.jsonl.gz", "JSONLines", True),
        ]
    )
    def test_matches_format(self, _name, key, file_format, expected):
        assert _matches_format(key, file_format) is expected


class TestEventRowMapping:
    def test_maps_all_clickhouse_columns_with_defaults(self):
        from posthog.local_bootstrap.importer import _EVENT_COLUMNS

        row = {
            "uuid": "11111111-1111-1111-1111-111111111111",
            "event": "$pageview",
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        mapped = _event_row_to_ch(row, team_id=42, now=datetime(2024, 1, 1))

        # Every column the INSERT lists must be present, or the block insert fails at runtime.
        assert set(mapped.keys()) == set(_EVENT_COLUMNS)
        assert mapped["team_id"] == 42
        # Missing person_id must fall back to the zero UUID, not "" (which the UUID column rejects).
        assert mapped["person_id"] == ZERO_UUID
        assert mapped["person_mode"] == "full"

    def test_coerces_null_properties_to_empty_string(self):
        row = {"uuid": "1" * 8 + "-1111-1111-1111-111111111111", "properties": None, "person_properties": None}
        mapped = _event_row_to_ch(row, team_id=1, now=datetime(2024, 1, 1))
        assert mapped["properties"] == ""
        assert mapped["person_properties"] == ""


class TestAccumulatePersons:
    def _run(self, monkeypatch, rows):
        monkeypatch.setattr(
            "posthog.local_bootstrap.importer.iter_table_rows",
            lambda config, files, batch_size, on_file_start=None: iter(rows),
        )
        return _accumulate_persons(_events_config(), files=[], batch_size=1000, progress=Progress())

    def test_collapses_multiple_distinct_ids_and_maxes_versions(self, monkeypatch):
        pid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        rows = [
            {
                "person_id": pid,
                "distinct_id": "d1",
                "properties": '{"a":1}',
                "person_version": 0,
                "person_distinct_id_version": 1,
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "person_id": pid,
                "distinct_id": "d2",
                "properties": '{"a":1}',
                "person_version": 3,
                "person_distinct_id_version": 0,
                "created_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        persons = self._run(monkeypatch, rows)
        assert set(persons.keys()) == {pid}
        assert persons[pid].version == 3
        assert persons[pid].distinct_ids == {"d1": 1, "d2": 0}

    def test_skips_rows_without_a_real_person_id(self, monkeypatch):
        rows = [
            {"person_id": "", "distinct_id": "d1"},
            {"person_id": ZERO_UUID, "distinct_id": "d2"},
        ]
        assert self._run(monkeypatch, rows) == {}

    def test_flags_deleted_persons(self, monkeypatch):
        pid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        rows = [{"person_id": pid, "distinct_id": "d1", "is_deleted": True, "properties": "{}"}]
        persons = self._run(monkeypatch, rows)
        assert persons[pid].is_deleted is True

    def test_parses_epoch_seconds_created_at(self, monkeypatch):
        # Persons dumps store created_at as uint32 epoch seconds, not a parquet timestamp; an int
        # here must not crash and must decode to the right instant.
        pid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        rows = [{"person_id": pid, "distinct_id": "d1", "properties": "{}", "created_at": 1_704_067_200}]
        persons = self._run(monkeypatch, rows)
        assert persons[pid].created_at == datetime(2024, 1, 1, tzinfo=UTC)
