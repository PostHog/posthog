import re
import sys
import argparse
import subprocess
from pathlib import Path, PurePosixPath

SCHEMA_INPUTS = (
    "uv.lock",
    "docker-compose.base.yml",
    "products/db_routing.yaml",
    "posthog/product_db_config.py",
    "posthog/product_db_router.py",
)
WORKFLOW_PATH = ".depot/workflows/ci-backend.yml"


class MasterSchemaCache:
    def __init__(self, repository: Path) -> None:
        self.repository = repository

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repository, check=True, capture_output=True, text=True, timeout=60
        ).stdout

    def _migration_files(self, revision: str) -> dict[str, str]:
        files: dict[str, str] = {}
        tree = self._git("ls-tree", "-r", "-z", "--format=%(objectname) %(path)", revision)
        for entry in tree.split("\0"):
            if not entry:
                continue
            object_id, filename = entry.split(" ", 1)
            path = PurePosixPath(filename)
            if path.parent.name != "migrations" or path.suffix != ".py":
                continue
            if path.parent.parent.name in {"clickhouse", "async_migrations"}:
                continue
            files[filename] = object_id
        return files

    def _incompatibility_reason(self, key: str, epoch: str) -> str | None:
        match = re.fullmatch(r"posthog-schema-master-([0-9a-f]{40})", key)
        if match is None:
            return "cache key is not a master snapshot"
        source = match.group(1)
        try:
            self._git("cat-file", "-e", f"{source}^{{commit}}")
        except subprocess.CalledProcessError:
            self._git("fetch", "--no-tags", "--depth=1", "--filter=blob:none", "origin", source)

        cached_epoch = None
        for line in self._git("show", f"{source}:{WORKFLOW_PATH}").splitlines():
            if line.startswith("    SCHEMA_CACHE_EPOCH:"):
                cached_epoch = line.split(":", 1)[1].strip()
                break
        if cached_epoch != epoch:
            return "cache epoch changed"

        changed_inputs = self._git("diff", "--name-only", source, "HEAD", "--", *SCHEMA_INPUTS).splitlines()
        if changed_inputs:
            return f"schema inputs changed: {', '.join(changed_inputs)}"

        current_migrations = self._migration_files("HEAD")
        # Reverts and squash retirement can change the meaning of recorded migrations.
        # New migrations are safe only when every cached migration still exists unchanged.
        for filename, object_id in self._migration_files(source).items():
            if current_migrations.get(filename) != object_id:
                return f"cached migration changed or was removed: {filename}"
        return None

    def validate(self, *, key: str, epoch: str, dump: Path) -> bool:
        try:
            reason = self._incompatibility_reason(key, epoch)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            reason = f"cannot read cached schema inputs: {error}"
        if reason is not None:
            # The restore step treats an existing dump as a cache hit.
            dump.unlink(missing_ok=True)
            sys.stdout.write(f"::notice::Discarded cached schema: {reason}; migrate will run from scratch\n")
            return False
        sys.stdout.write("Cached master schema is compatible; migrate will apply the missing migrations\n")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Discard master schema dumps that cannot be migrated forward safely")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--epoch", required=True)
    args = parser.parse_args()
    MasterSchemaCache(args.repository).validate(key=args.cache_key, epoch=args.epoch, dump=args.dump)


if __name__ == "__main__":
    main()
