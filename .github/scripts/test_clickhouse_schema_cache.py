import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import clickhouse_schema_cache
from clickhouse_schema_cache import (
    SHARED_INPUTS,
    SnapshotError,
    _other_databases,
    fingerprint,
    incompatibility,
    load,
    operation_text,
)
from parameterized import parameterized

REPOSITORY = Path(__file__).resolve().parents[2]

CACHED = {
    "inputs": {"epoch": "v1", "image": "clickhouse:1", "uv.lock": "a"},
    "migrations": {"0001_initial": "x", "0002_events": "y"},
}


def _checkout(inputs: dict | None = None, migrations: dict | None = None, drop: str | None = None) -> dict:
    result = {
        "inputs": {**CACHED["inputs"], **(inputs or {})},
        "migrations": {**CACHED["migrations"], **(migrations or {})},
    }
    if drop:
        del result["migrations"][drop]
    return result


@parameterized.expand(
    [
        ("identical", _checkout(), None),
        ("new migrations are topped up", _checkout(migrations={"0003_new": "z"}), None),
        ("shared input changed", _checkout(inputs={"uv.lock": "b"}), "shared input changed: uv.lock"),
        ("shared input added", _checkout(inputs={"new.py": "c"}), "shared input changed: new.py"),
        (
            "snapshot newer than checkout",
            _checkout(drop="0002_events"),
            "snapshot has a migration this checkout lacks: 0002_events",
        ),
        (
            "migration renders other SQL",
            _checkout(migrations={"0001_initial": "changed"}),
            "migration renders different SQL in this checkout: 0001_initial",
        ),
    ]
)
def test_incompatibility(_name: str, checkout: dict, expected: str | None) -> None:
    assert incompatibility(CACHED, checkout) == expected


def test_operation_text_ignores_random_zookeeper_paths_but_not_sql() -> None:
    first = SimpleNamespace(_sql="ENGINE = ReplicatedMergeTree('/t/0a1b2c3d-0000-4000-8000-000000000001/x', 'r')")
    second = SimpleNamespace(_sql="ENGINE = ReplicatedMergeTree('/t/9f8e7d6c-1111-4111-8111-111111111111/x', 'r')")
    assert operation_text(first) == operation_text(second)
    assert operation_text(SimpleNamespace(_sql=["a", "b"])) != operation_text(SimpleNamespace(_sql=["a", "c"]))


def test_other_databases_skips_the_test_database_and_functions() -> None:
    snapshot = "database\tposthog_test\tAtomic\ntable\tposthog_test\tevents\nfunction\tf\tq\ntable\tdefault\tt\n"
    assert _other_databases(snapshot) == ["table\tdefault\tt"]


def test_shared_inputs_all_exist_so_a_rename_cannot_silently_drop_one() -> None:
    assert [path for path in SHARED_INPUTS if not (REPOSITORY / path).exists()] == []


@pytest.mark.parametrize("path", ["posthog/models/performance/sql.py", "posthog/settings/dynamic_settings.py"])
def test_fingerprint_rejects_a_changed_runpython_dependency(
    path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "posthog.settings")
    monkeypatch.setitem(sys.modules, "django", SimpleNamespace(setup=lambda: None))
    monkeypatch.setitem(
        sys.modules, "infi.clickhouse_orm.utils", SimpleNamespace(import_submodules=lambda _package: {})
    )
    dependency = tmp_path / path
    dependency.parent.mkdir(parents=True)
    dependency.write_text("before")
    cached = fingerprint(tmp_path, "v1", "clickhouse:1")
    dependency.write_text("after")
    checkout = fingerprint(tmp_path, "v1", "clickhouse:1")
    assert incompatibility(cached, checkout) == f"shared input changed: {path}"


def _snapshot_dir(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "snapshot"
    directory.mkdir()
    (directory / "fingerprint.json").write_text('{"inputs": {}, "migrations": {}}')
    checkout = tmp_path / "checkout.json"
    checkout.write_text('{"inputs": {}, "migrations": {}}')
    return directory, checkout


def _failing(*_args: object, **_kwargs: object) -> None:
    raise SnapshotError("boom")


def test_load_is_a_miss_when_the_failed_restore_is_cleaned_up(tmp_path, monkeypatch) -> None:
    directory, checkout = _snapshot_dir(tmp_path)
    resets = []
    monkeypatch.setattr(clickhouse_schema_cache, "_restore", _failing)
    monkeypatch.setattr(clickhouse_schema_cache, "reset", lambda: resets.append(1))
    assert load(directory, checkout) is False
    assert resets == [1]


def test_load_raises_when_the_cleanup_after_a_failed_restore_fails(tmp_path, monkeypatch) -> None:
    directory, checkout = _snapshot_dir(tmp_path)
    monkeypatch.setattr(clickhouse_schema_cache, "_restore", _failing)
    monkeypatch.setattr(clickhouse_schema_cache, "reset", _failing)
    with pytest.raises(SnapshotError, match="could not clean up"):
        load(directory, checkout)
