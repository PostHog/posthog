import re
import sys
import hashlib
import argparse
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

WORKFLOW_PATH = ".depot/workflows/ci-backend.yml"
DB_ROUTING_PATHS = frozenset(
    {"products/db_routing.yaml", "posthog/product_db_config.py", "posthog/product_db_router.py"}
)
DJANGO_MIGRATION = re.compile(r"/migrations/[^/]+\.py$")
NON_DJANGO_MIGRATION = re.compile(r"/(clickhouse|async_migrations)/migrations/")
POSTGRES_IMAGE = re.compile(r"[ \t\n\v\f\r]*image:[ \t\n\v\f\r]*postgres:")
WHITESPACE = re.compile(r"[ \t\n\v\f\r]")
MASTER_SNAPSHOT_KEY = re.compile(r"posthog-schema-master-([0-9a-f]{40})")


class GitError(Exception):
    pass


class GitRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, *args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=self.path, check=True, capture_output=True, text=True, timeout=60
            ).stdout
        except subprocess.CalledProcessError as error:
            raise GitError(f"git {args[0]} failed: {error.stderr.strip()}") from error

    def has_commit(self, revision: str) -> bool:
        probe = ["git", "cat-file", "-e", f"{revision}^{{commit}}"]
        return subprocess.run(probe, cwd=self.path, capture_output=True, timeout=60).returncode == 0

    def files(self, revision: str) -> dict[str, str]:
        files: dict[str, str] = {}
        for entry in self.run("ls-tree", "-r", "-z", "--format=%(objectname) %(path)", revision).split("\0"):
            if entry:
                blob, path = entry.split(" ", 1)
                files[path] = blob
        return files


@dataclass(frozen=True, kw_only=True, slots=True)
class SchemaInputs:
    migrations: Mapping[str, str]
    uv_lock: str | None
    postgres_image: str
    db_routing: str

    @classmethod
    def read(cls, repository: GitRepository, revision: str) -> "SchemaInputs":
        files = repository.files(revision)
        compose = (
            repository.run("cat-file", "blob", files["docker-compose.base.yml"])
            if "docker-compose.base.yml" in files
            else ""
        )
        postgres_image = next((line for line in compose.split("\n") if POSTGRES_IMAGE.match(line)), "")
        return cls(
            migrations={
                path: blob
                for path, blob in files.items()
                if DJANGO_MIGRATION.search(path) and not NON_DJANGO_MIGRATION.search(path)
            },
            uv_lock=files.get("uv.lock"),
            postgres_image=WHITESPACE.sub("", postgres_image),
            db_routing="\n".join(f"{blob} {path}" for path, blob in files.items() if path in DB_ROUTING_PATHS),
        )

    def cache_key(self, epoch: str) -> str | None:
        # Other workflows compute this key in shell to restore the same dumps, so a change to
        # these bytes makes their exact restores miss.
        locked_files = [f"{blob} {path}" for path, blob in self.migrations.items()]
        if self.uv_lock is not None:
            locked_files.append(f"{self.uv_lock} uv.lock")
        if not locked_files:
            return None
        fingerprint = "\n".join(["\n".join(sorted(locked_files)), self.postgres_image, self.db_routing])
        return f"posthog-schema-mig-{epoch}-{hashlib.sha256(fingerprint.encode()).hexdigest()[:40]}"

    def incompatibility_with(self, checkout: "SchemaInputs") -> str | None:
        if self.postgres_image != checkout.postgres_image:
            return "Postgres image changed"
        if self.uv_lock != checkout.uv_lock:
            return "uv.lock changed"
        if self.db_routing != checkout.db_routing:
            return "database routing changed"
        # Reverts and squash retirement can change the meaning of recorded migrations.
        # New migrations are safe only when every cached migration still exists unchanged.
        for path, blob in self.migrations.items():
            if checkout.migrations.get(path) != blob:
                return f"cached migration changed or was removed: {path}"
        return None


class MasterSchemaCache:
    def __init__(self, checkout: Path) -> None:
        self.repository = GitRepository(checkout)

    def key(self, *, epoch: str) -> str | None:
        return SchemaInputs.read(self.repository, "HEAD").cache_key(epoch)

    def validate(self, *, key: str, epoch: str, dump: Path) -> bool:
        try:
            reason = self._incompatibility_reason(key, epoch)
        # Discarding is always safe and a crash fails the job, so any error that stops
        # the proof of compatibility discards the dump.
        except Exception as error:
            reason = f"cannot read cached schema inputs: {type(error).__name__}: {error}"
        if reason is not None:
            # The restore step treats an existing dump as a cache hit.
            dump.unlink(missing_ok=True)
            sys.stdout.write(f"::notice::Discarded cached schema: {reason}; migrate will run from scratch\n")
            return False
        sys.stdout.write("Cached master schema is compatible; migrate will apply the missing migrations\n")
        return True

    def _incompatibility_reason(self, key: str, epoch: str) -> str | None:
        match = MASTER_SNAPSHOT_KEY.fullmatch(key)
        if match is None:
            return "cache key is not a master snapshot"
        source = match.group(1)
        if not self.repository.has_commit(source):
            # A --filter fetch would turn the checkout into a partial clone for every later step.
            # A depth-1 fetch only transfers the objects that HEAD's tree lacks.
            self.repository.run("fetch", "--no-tags", "--depth=1", "origin", source)
        if self._epoch(source) != epoch:
            return "cache epoch changed"
        return SchemaInputs.read(self.repository, source).incompatibility_with(
            SchemaInputs.read(self.repository, "HEAD")
        )

    def _epoch(self, revision: str) -> str | None:
        workflow = yaml.safe_load(self.repository.run("show", f"{revision}:{WORKFLOW_PATH}"))
        epoch = workflow.get("env", {}).get("SCHEMA_CACHE_EPOCH")
        return None if epoch is None else str(epoch)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and validate master schema dump cache keys")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--epoch", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("key", help="Print the migration-set cache key of HEAD, or an empty line")
    validate = commands.add_parser("validate", help="Discard a master snapshot that HEAD cannot migrate forward")
    validate.add_argument("--dump", type=Path, required=True)
    validate.add_argument("--cache-key", required=True)
    args = parser.parse_args()

    cache = MasterSchemaCache(args.repository)
    if args.command == "key":
        sys.stdout.write(f"{cache.key(epoch=args.epoch) or ''}\n")
    else:
        cache.validate(key=args.cache_key, epoch=args.epoch, dump=args.dump)


if __name__ == "__main__":
    main()
