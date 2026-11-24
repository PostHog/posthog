from types import SimpleNamespace

from clickhouse_schema_cache import _other_databases, incompatibility, operation_text
from parameterized import parameterized

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
