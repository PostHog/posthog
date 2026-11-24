"""Cache the ClickHouse schema that `migrate_clickhouse` builds, and restore it in later CI jobs.

ClickHouse migrations render their DDL from live model code (e.g. EVENTS_TABLE_SQL()), so the
migration files alone do not pin the schema. The fingerprint of each migration therefore covers
its module source and the SQL its operations would run. A snapshot is used only when every
migration it recorded has the same fingerprint in the checkout; `migrate_clickhouse` then applies
the checkout's extra migrations on top. Anything else is a miss and migrates from scratch.

The snapshot is a ClickHouse BACKUP of the test database, which keeps dictionary credentials,
dependency order and seed rows, plus the SQL user-defined functions, which live outside it.
`save` only writes the snapshot directory after restoring it and finding the schema identical to the one
the full migrate built.
"""

import os
import re
import sys
import json
import shutil
import hashlib
import argparse
import tempfile
import subprocess
from pathlib import Path

# Test engines put a random uuid4 in every ZooKeeper path, so the raw SQL differs per process.
UUID_SQL = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID = re.compile(UUID_SQL)
MIGRATIONS_PACKAGE = "posthog.clickhouse.migrations"
# Files that change how every migration is applied, rather than what one migration says.
SHARED_INPUTS = (
    "posthog/management/commands/migrate_clickhouse.py",
    "posthog/clickhouse/client/migration_tools.py",
    "posthog/clickhouse/cluster.py",
    "uv.lock",
)
DATABASE = "posthog_test"
BACKUP_DISK = "ci_schema_cache"  # .github/clickhouse-schema-cache/backup-disk.xml
BACKUP_DIR = "/var/lib/clickhouse/ci_schema_cache"
BACKUP_NAME = "snapshot"
USER_DATABASES = "database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')"
# ops_query_log_archive_v3_mv copies system.query_log into these, so their row counts move with
# every query the server runs, this snapshot's included.
QUERY_LOG_TABLES = ("query_log_archive_v3_buffer", "sharded_query_log_archive_v3")
SNAPSHOT_QUERIES = (
    "SELECT 'database', name, engine FROM system.databases WHERE name NOT IN "
    "('system', 'information_schema', 'INFORMATION_SCHEMA') ORDER BY ALL",
    f"SELECT 'table', database, replaceRegexpAll(name, '{UUID_SQL}', '<uuid>'), engine, "
    f"replaceRegexpAll(create_table_query, '{UUID_SQL}', '<uuid>'), "
    f"if(name IN {QUERY_LOG_TABLES}, '', toString(total_rows)) "
    f"FROM system.tables WHERE {USER_DATABASES} ORDER BY ALL",
    f"SELECT 'column', database, replaceRegexpAll(table, '{UUID_SQL}', '<uuid>'), position, name, type, "
    f"default_kind, default_expression, compression_codec FROM system.columns WHERE {USER_DATABASES} ORDER BY ALL",
    # Masked credentials make a broken dictionary look identical in SHOW CREATE; loading it does not.
    "SELECT 'dictionary', database, name, status FROM system.dictionaries ORDER BY ALL",
    "SELECT 'function', name, create_query FROM system.functions WHERE origin = 'SQLUserDefined' ORDER BY ALL",
)


class SnapshotError(Exception):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _notice(message: str) -> None:
    sys.stdout.write(f"::notice::{message}\n")
    sys.stdout.flush()


# --- fingerprints -----------------------------------------------------------------------------


def operation_text(operation: object) -> str:
    sql = getattr(operation, "_sql", None)
    if sql is None:
        # Custom RunPython operations: their code is covered by the module source hash.
        return f"<{type(operation).__name__}>"
    statements = [sql] if isinstance(sql, str) else list(sql)
    return "\n;\n".join(UUID.sub("<uuid>", statement) for statement in statements)


def fingerprint(repository: Path, epoch: str, image: str) -> dict:
    sys.path[:0] = [str(repository), str(repository / "common")]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()
    from infi.clickhouse_orm.utils import import_submodules

    migrations = {}
    for name, module in sorted(import_submodules(MIGRATIONS_PACKAGE).items()):
        parts = [_sha256(Path(module.__file__).read_bytes())]
        parts += [operation_text(operation) for operation in getattr(module, "operations", [])]
        migrations[name] = _sha256("\n--\n".join(parts).encode())
    inputs: dict[str, str | None] = {"epoch": epoch, "image": image}
    for path in SHARED_INPUTS:
        file = repository / path
        inputs[path] = _sha256(file.read_bytes()) if file.exists() else None
    return {"inputs": inputs, "migrations": migrations}


def incompatibility(cached: dict, checkout: dict) -> str | None:
    for name, value in cached["inputs"].items():
        if checkout["inputs"].get(name) != value:
            return f"shared input changed: {name}"
    for name, value in cached["migrations"].items():
        if name not in checkout["migrations"]:
            return f"snapshot has a migration this checkout lacks: {name}"
        if checkout["migrations"][name] != value:
            return f"migration renders different SQL in this checkout: {name}"
    return None


# --- ClickHouse ---------------------------------------------------------------------------------


COMPOSE = ("docker", "compose", "-f", "docker-compose.dev.yml")
SERVICE = "clickhouse"


def _run(command: list[str], stdin: bytes | None = None) -> bytes:
    result = subprocess.run(command, input=stdin, capture_output=True, timeout=600, check=False)
    if result.returncode != 0:
        raise SnapshotError(
            f"{' '.join(command)[:200]} failed: {result.stderr.decode(errors='replace').strip()[-2000:]}"
        )
    return result.stdout


def _container(*args: str, stdin: bytes | None = None, user: str | None = None) -> bytes:
    command = [*COMPOSE, "exec", "-T"]
    if user:
        command += ["--user", user]
    return _run([*command, SERVICE, *args], stdin=stdin)


def _copy(source: str, destination: str) -> None:
    # `docker compose cp` streams the files itself, so no archive is unpacked on the runner.
    _run([*COMPOSE, "cp", source, destination])


def _query(sql: str) -> str:
    return _container("clickhouse-client", "--query", sql).decode()


def snapshot() -> str:
    try:
        _query("SYSTEM RELOAD DICTIONARIES")
    except SnapshotError:
        pass  # A dictionary that fails to load shows as FAILED below.
    return "".join(_query(f"{sql} FORMAT TSV") for sql in SNAPSHOT_QUERIES)


def _sql_functions() -> list[str]:
    return _query("SELECT name FROM system.functions WHERE origin = 'SQLUserDefined' FORMAT TSV").split()


def reset() -> None:
    _query(f"DROP DATABASE IF EXISTS {DATABASE} SYNC")
    for name in _sql_functions():
        _query(f"DROP FUNCTION IF EXISTS `{name}`")


def _restore(directory: Path) -> None:
    _container("sh", "-c", f"rm -rf {BACKUP_DIR}/{BACKUP_NAME} && mkdir -p {BACKUP_DIR}", user="root")
    _copy(str(directory / BACKUP_NAME), f"{SERVICE}:{BACKUP_DIR}/{BACKUP_NAME}")
    _container("chown", "-R", "clickhouse:clickhouse", BACKUP_DIR, user="root")
    # Tables can call SQL functions, so the functions go first.
    functions = (directory / "functions.sql").read_text()
    if functions.strip():
        _container("clickhouse-client", "--multiquery", stdin=functions.encode())
    _query(f"RESTORE DATABASE {DATABASE} FROM Disk('{BACKUP_DISK}', '{BACKUP_NAME}')")
    # Restored dictionaries load lazily, and SYSTEM RELOAD DICTIONARIES skips those never loaded.
    # Load the ones the migrations loaded, so a broken one fails here rather than in a test.
    for name in (directory / "dictionaries.txt").read_text().split():
        _query(f"SYSTEM RELOAD DICTIONARY {name}")


def load(directory: Path, checkout: Path) -> bool:
    try:
        reason = incompatibility(
            json.loads((directory / "fingerprint.json").read_text()), json.loads(checkout.read_text())
        )
    except Exception as error:
        reason = f"cannot read the snapshot: {type(error).__name__}: {error}"
    if reason is not None:
        _notice(f"Discarded cached ClickHouse schema: {reason}; migrating from scratch")
        return False
    try:
        _restore(directory)
    except Exception as error:
        _notice(f"ClickHouse schema restore failed ({error}); migrating from scratch")
        reset()
        return False
    sys.stdout.write("Restored the cached ClickHouse schema; migrate_clickhouse applies what it lacks\n")
    return True


def _other_databases(text: str) -> list[str]:
    # Rows for objects outside the test database. The BACKUP covers only that database.
    rows = [line.split("\t") for line in text.splitlines()]
    return ["\t".join(row) for row in rows if row[0] != "function" and row[1:2] != [DATABASE]]


def save(checkout: Path, before: Path, out: Path) -> None:
    """Write the migrated schema to `out`, once a restore of it has been proven identical.

    `out` appears only when the snapshot is complete. Never fails while the migrated schema is
    intact. Once it has been dropped, a failure rebuilds it from scratch, and only a failed
    rebuild fails the job.
    """
    with tempfile.TemporaryDirectory(dir=out.parent) as work:
        directory = Path(work) / "snapshot"
        directory.mkdir()
        try:
            migrated = _backup(directory, checkout, before)
        except Exception as error:
            _notice(f"Not caching the ClickHouse schema: {error}")
            return
        try:
            reset()
            _restore(directory)
            restored = snapshot()
        except Exception as error:
            _notice(f"Not caching the ClickHouse schema: restoring it failed ({error})")
            _rebuild()
            return
        if restored != migrated:
            diff = sorted(set(migrated.splitlines()) ^ set(restored.splitlines()))
            sys.stdout.write(
                "Rows that differ between the migrated and the restored schema:\n" + "\n".join(diff) + "\n"
            )
            _notice(f"Not caching the ClickHouse schema: the restore differs from the migrate in {len(diff)} rows")
            _rebuild()
            return
        shutil.rmtree(out, ignore_errors=True)
        directory.rename(out)
    sys.stdout.write(f"Restore reproduced the migrated schema ({len(migrated.splitlines())} rows); saved it\n")


def _backup(directory: Path, checkout: Path, before: Path) -> str:
    migrated = snapshot()
    outside = sorted(set(_other_databases(migrated)) ^ set(_other_databases(before.read_text())))
    if outside:
        raise SnapshotError(f"migrations changed objects outside {DATABASE}: {outside[:3]}")
    _container("sh", "-c", f"rm -rf {BACKUP_DIR}/{BACKUP_NAME}", user="root")
    _query(f"BACKUP DATABASE {DATABASE} TO Disk('{BACKUP_DISK}', '{BACKUP_NAME}')")
    functions = _query(
        "SELECT create_query || ';' FROM system.functions WHERE origin = 'SQLUserDefined' ORDER BY name FORMAT TSVRaw"
    )
    (directory / "functions.sql").write_text(functions)
    loaded = _query(
        "SELECT backQuote(database) || '.' || backQuote(name) FROM system.dictionaries "
        f"WHERE database = '{DATABASE}' AND status = 'LOADED' ORDER BY ALL FORMAT TSVRaw"
    )
    (directory / "dictionaries.txt").write_text(loaded)
    shutil.copy(checkout, directory / "fingerprint.json")
    _copy(f"{SERVICE}:{BACKUP_DIR}/{BACKUP_NAME}", str(directory / BACKUP_NAME))
    return migrated


def _rebuild() -> None:
    reset()
    subprocess.run([sys.executable, "manage.py", "migrate_clickhouse"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fp = commands.add_parser("fingerprint", help="Write the checkout's fingerprint and print its digest")
    fp.add_argument("--epoch", required=True)
    fp.add_argument("--image", required=True)
    fp.add_argument("--out", type=Path, required=True)
    snap = commands.add_parser("snapshot", help="Write the normalized schema of every user database")
    snap.add_argument("--out", type=Path, required=True)
    ld = commands.add_parser("load", help="Restore a compatible snapshot; exit 1 on a miss, leaving no schema")
    ld.add_argument("--snapshot", type=Path, required=True)
    ld.add_argument("--checkout", type=Path, required=True)
    sv = commands.add_parser("save", help="Save the migrated schema after proving a restore reproduces it")
    sv.add_argument("--checkout", type=Path, required=True)
    sv.add_argument("--before", type=Path, required=True)
    sv.add_argument("--out", type=Path, required=True)
    commands.add_parser("reset", help="Drop the test database and SQL functions")
    args = parser.parse_args()

    if args.command == "fingerprint":
        payload = json.dumps(fingerprint(Path.cwd(), args.epoch, args.image), indent=1, sort_keys=True)
        args.out.write_text(payload)
        sys.stdout.write(f"{_sha256(payload.encode())[:40]}\n")
    elif args.command == "snapshot":
        args.out.write_text(snapshot())
    elif args.command == "load":
        sys.exit(0 if load(args.snapshot, args.checkout) else 1)
    elif args.command == "save":
        save(args.checkout, args.before, args.out)
    else:
        reset()


if __name__ == "__main__":
    main()
