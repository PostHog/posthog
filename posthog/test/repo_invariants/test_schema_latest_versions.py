import json
from pathlib import Path

from posthog.schema_migrations import LATEST_VERSIONS, _discover_migrations
from posthog.utils import to_json


def test_frontend_latest_versions_file_in_sync():
    _discover_migrations()

    path = Path(__file__).parents[3] / "frontend" / "src" / "queries" / "schema" / "latest-versions.json"
    committed = json.loads(path.read_text())
    committed.pop("//", None)

    # Serialize the same way bin/build-schema-latest-versions.py does
    expected = json.loads(to_json(LATEST_VERSIONS))

    assert committed == expected, (
        "frontend/src/queries/schema/latest-versions.json is out of sync with posthog/schema_migrations. "
        "Run `python bin/build-schema-latest-versions.py` (part of `pnpm run schema:build` / `hogli build:schema`) "
        "and commit the result."
    )
