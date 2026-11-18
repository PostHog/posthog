"""Guard: a local ClickHouse Kafka table must declare exactly one consumer.

The local stacks create every topic with one partition, so a consumer group can
place only one consumer. Extra consumers never get an assignment. Each one holds
a thread and repeats the request for as long as the stack runs, which burns CPU
and floods the server log.

Two declarations can put a table on a local stack, so this guards both.

The generated SQL under posthog/clickhouse/hcl/sql/local-* is the artifact the
local stacks converge on, so it is the one place that sees a table however it was
declared: directly in a local layer, or in a shared layer a local stack composes.

The Python DDL builds the dev stack and does not reach that SQL, so a table whose
CREATE hardcodes a count above one regresses without moving a golden. A call site
that wants more than one consumer on cloud must ask kafka_num_consumers(), which
returns the tuned count there and one everywhere else. A hardcoded one is correct
as it stands and stays allowed.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
LOCAL_SQL_DIRS = ("local-single", "local-multi")
# hogli clickhouse:logs:init runs this straight at a local server, so it never
# reaches the generated SQL and needs reading on its own.
EXTRA_LOCAL_SQL = ("bin/clickhouse-logs.sql",)

# The generator prints one CREATE per statement and orders the settings, so the
# table name and its consumer count are both on the statement's own line.
_CREATE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?(?:[\w.]*?\.)?(\w+)", re.IGNORECASE)
_KAFKA_CONSUMERS = re.compile(r"ENGINE = Kafka\(.*?kafka_num_consumers = (\d+)", re.DOTALL)


def _local_sql_files() -> list[tuple[str, Path]]:
    files = [
        (env, path)
        for env in LOCAL_SQL_DIRS
        for path in sorted((REPO_ROOT / "posthog" / "clickhouse" / "hcl" / "sql" / env).glob("*.sql"))
    ]
    files += [(name, REPO_ROOT / name) for name in EXTRA_LOCAL_SQL]
    return files


def _offenders() -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for source, path in _local_sql_files():
        for statement in path.read_text().split(";"):
            consumers = _KAFKA_CONSUMERS.search(statement)
            if consumers is None:
                continue
            count = int(consumers.group(1))
            if count != 1:
                name = _CREATE.search(statement)
                found.append((source, name.group(1) if name else "<unknown>", count))
    return found


def test_local_kafka_tables_declare_one_consumer() -> None:
    offenders = _offenders()

    assert not offenders, (
        "These Kafka tables declare more than one consumer on a local stack: "
        + ", ".join(f"{source}/{table} = {count}" for source, table, count in offenders)
        + ". Local topics have one partition, so the extra consumers never get an assignment and "
        "spin instead. Lower the count for the local envs: patch_table the engine in the local "
        "layer the stack composes, then rerun posthog/clickhouse/hcl/gen-golden.sh and gen-sql.sh."
    )


def test_the_guard_reads_some_kafka_tables() -> None:
    # A regex that silently matches nothing would make the guard above vacuous.
    counts = [m.group(1) for _, path in _local_sql_files() for m in _KAFKA_CONSUMERS.finditer(path.read_text())]

    assert len(counts) >= 10, f"expected the local goldens to hold Kafka tables, parsed {len(counts)}"


# The DDL lives in f-string templates, so a call reads "{kafka_num_consumers(8)}"
# and only a hardcoded count is a bare integer. The prefix is optional because one
# template carries a "{num_consumers}" placeholder that its caller fills separately.
_HARDCODED = re.compile(r"num_consumers\s*=\s*(\d+)")

SEARCH_ROOTS = ("posthog", "products", "ee")


def test_python_ddl_does_not_hardcode_extra_consumers() -> None:
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "test" in path.parts or path.name.startswith("test_"):
                continue
            text = path.read_text()
            # Almost no file names the setting, so read lines only for the few that do.
            if "kafka_num_consumers" not in text:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                found = _HARDCODED.search(line)
                if found and int(found.group(1)) != 1:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not offenders, (
        "These lines hardcode a Kafka consumer count: "
        + ", ".join(offenders)
        + ". A local topic has one partition, so a fixed count above one leaves consumers that "
        "never get an assignment and spin. Call kafka_num_consumers(<cloud count>) from "
        "posthog.clickhouse.kafka_engine instead, which keeps the tuned count on cloud."
    )
