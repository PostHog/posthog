import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import NodeKind

import posthog.schema_migrations as schema_migrations_module
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, _discover_migrations
from posthog.utils import to_json


def _discover_with_mocks(files: list[str], modules: list[MagicMock]) -> None:
    with (
        patch("posthog.schema_migrations.os.listdir") as mock_listdir,
        patch("posthog.schema_migrations.importlib.import_module") as mock_import,
    ):
        mock_listdir.return_value = files
        mock_import.side_effect = modules
        schema_migrations_module._migrations_discovered = False
        _discover_migrations()


@pytest.fixture(autouse=True)
def _reset_migration_state():
    # Restore pristine state so tests running later in the process re-discover the real migrations
    yield
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()
    schema_migrations_module._migrations_discovered = False


def test_discover_migrations():
    mock_module1 = MagicMock()
    mock_module1.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 1}

    mock_module2 = MagicMock()
    mock_module2.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 2, NodeKind.FUNNELS_QUERY: 1}

    _discover_with_mocks(["0001_test.py", "0002_another.py", "not_a_migration.py"], [mock_module1, mock_module2])

    assert LATEST_VERSIONS[NodeKind.TRENDS_QUERY] == 3  # Max version + 1
    assert LATEST_VERSIONS[NodeKind.FUNNELS_QUERY] == 2  # Version + 1

    assert MIGRATIONS[NodeKind.TRENDS_QUERY][1] == mock_module1.Migration.return_value
    assert MIGRATIONS[NodeKind.TRENDS_QUERY][2] == mock_module2.Migration.return_value
    assert MIGRATIONS[NodeKind.FUNNELS_QUERY][1] == mock_module2.Migration.return_value


def test_discover_migrations_rejects_duplicate_targets():
    mock_module1 = MagicMock()
    mock_module1.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 1}

    mock_module2 = MagicMock()
    mock_module2.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 1}

    with pytest.raises(ValueError, match="Duplicate schema migration target"):
        _discover_with_mocks(["0001_test.py", "0002_another.py"], [mock_module1, mock_module2])


def test_discover_migrations_recovers_after_failed_discovery():
    bad_module = MagicMock()
    bad_module.Migration.side_effect = RuntimeError("broken migration module")

    with pytest.raises(RuntimeError):
        _discover_with_mocks(["0001_test.py"], [bad_module])

    good_module = MagicMock()
    good_module.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 1}

    _discover_with_mocks(["0001_test.py"], [good_module])

    assert LATEST_VERSIONS[NodeKind.TRENDS_QUERY] == 2


def test_frontend_latest_versions_file_in_sync():
    _discover_migrations()

    path = Path(__file__).parents[3] / "frontend" / "src" / "queries" / "latest-versions.json"
    committed = json.loads(path.read_text())
    committed.pop("//", None)

    # Serialize the same way bin/build-schema-latest-versions.py does
    expected = json.loads(to_json(LATEST_VERSIONS))

    assert committed == expected, (
        "frontend/src/queries/latest-versions.json is out of sync with posthog/schema_migrations. "
        "Run `python bin/build-schema-latest-versions.py` (part of `pnpm run schema:build` / `hogli build:schema`) "
        "and commit the result."
    )
