import sys
import glob
import json
import subprocess
from pathlib import Path
from typing import Any

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from posthog.schema_migrations.upgrade import upgrade

MOCKS_DIR = Path(__file__).resolve().parents[2] / "frontend/src/mocks/fixtures/api/projects/team_id/insights"


def migrate_file(filepath):
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    # If the file contains a list of queries, migrate each; else, migrate the dict
    migrated: list[dict[Any, Any]] | dict[Any, Any]
    if isinstance(data, list):
        migrated = [upgrade(query) for query in data]
    else:
        migrated = upgrade(data)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=4, ensure_ascii=False)
    print(f"Migrated: {filepath}")  # noqa: T201


def main():
    files = glob.glob(str(MOCKS_DIR / "*.json"))
    for filepath in files:
        migrate_file(filepath)

    subprocess.run(
        ["pnpm", "prettier", "--write", MOCKS_DIR],
    )


if __name__ == "__main__":
    main()
