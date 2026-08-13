import re
from dataclasses import dataclass
from pathlib import Path

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DatabaseField,
    ExpressionField,
    FunctionCallTable,
    LazyTable,
    SavedQuery,
    Table,
    VirtualTable,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tags_context

BASELINE_PATH = Path(__file__).parent / "nullability_drift_baseline.txt"

# A table backed by a subquery, an S3 file, or a table function has no `system.columns` row to
# compare against, so only tables mapping to a physical ClickHouse table are checked.
NON_PHYSICAL_TABLE_TYPES = (LazyTable, VirtualTable, FunctionCallTable, SavedQuery)

_LOW_CARDINALITY = re.compile(r"LowCardinality\((.*)\)")
_SIMPLE_AGGREGATE = re.compile(r"SimpleAggregateFunction\([^,]+,\s*(.*)\)")


# Whether reading a column of this type can yield NULL. `LowCardinality` and
# `SimpleAggregateFunction` wrap a value that reads back as its inner type, so
# `LowCardinality(Nullable(String))` is every bit as nullable as `Nullable(String)`.
# `Array(Nullable(String))` is not — the array itself is always present.
def clickhouse_type_is_nullable(clickhouse_type: str) -> bool:
    previous = None
    while previous != clickhouse_type:
        previous = clickhouse_type
        for pattern in (_LOW_CARDINALITY, _SIMPLE_AGGREGATE):
            match = pattern.fullmatch(clickhouse_type)
            if match:
                clickhouse_type = match.group(1)
                break
    return clickhouse_type.startswith("Nullable(")


def read_baseline() -> set[str]:
    entries = set()
    for line in BASELINE_PATH.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


@dataclass(frozen=True, kw_only=True)
class DriftReport:
    # `table.column` -> why it disagrees, for every field checked against a real column.
    drift: dict[str, str]
    # Every `table.column` we were able to compare, drifting or not.
    compared: set[str]


class TestNullabilityDrift(ClickhouseTestMixin, BaseTest):
    def _collect(self) -> DriftReport:
        database = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, database=database, enable_select_queries=True)

        with tags_context(product="internal", feature="schema_introspection"):
            rows = sync_execute("SELECT table, name, type FROM system.columns WHERE database = currentDatabase()")
        clickhouse_columns: dict[tuple[str, str], str] = {(table, name): type_ for table, name, type_ in rows}
        clickhouse_tables = {table for table, _ in clickhouse_columns}

        drift: dict[str, str] = {}
        compared: set[str] = set()

        for table_name in database.tables.resolve_all_table_names():
            try:
                table = database.get_table(table_name)
            except Exception:
                continue
            if not isinstance(table, Table) or isinstance(table, NON_PHYSICAL_TABLE_TYPES):
                continue
            try:
                clickhouse_table = table.to_printed_clickhouse(context).strip("`")
            except Exception:
                continue
            if clickhouse_table not in clickhouse_tables:
                continue

            for field in table.fields.values():
                if not isinstance(field, DatabaseField) or isinstance(field, ExpressionField):
                    continue
                clickhouse_type = clickhouse_columns.get((clickhouse_table, field.name))
                if clickhouse_type is None:
                    continue
                # An aggregate state column reads back as whatever merging it produces, which is
                # what the field already declares. Comparing the two would mean modeling the
                # return type of every aggregate function.
                if clickhouse_type.startswith("AggregateFunction("):
                    continue

                key = f"{clickhouse_table}.{field.name}"
                compared.add(key)
                if clickhouse_type_is_nullable(clickhouse_type) != field.is_nullable():
                    declared = "nullable" if field.is_nullable() else "non-nullable"
                    drift[key] = f"declared {declared}, ClickHouse stores {clickhouse_type}"

        return DriftReport(drift=drift, compared=compared)

    def test_declared_nullability_matches_clickhouse(self) -> None:
        report = self._collect()
        baseline = read_baseline()

        # Without a floor this test passes vacuously the moment table names stop lining up with
        # `system.columns` — say if `to_printed_clickhouse` starts qualifying them with a database.
        # The real count is several hundred; this only catches the mapping breaking wholesale.
        assert len(report.compared) > 200, (
            f"Only {len(report.compared)} columns could be matched to ClickHouse, so this check is "
            "no longer testing anything. Table names from `to_printed_clickhouse` most likely "
            "stopped matching `system.columns`."
        )

        new_drift = sorted(set(report.drift) - baseline)
        # Only entries we actually compared can be called stale — a table missing from this
        # ClickHouse was never checked, so its baseline entry tells us nothing either way.
        stale = sorted(entry for entry in baseline & report.compared if entry not in report.drift)

        problems = []
        if new_drift:
            problems.append(
                "These fields declare a nullability ClickHouse disagrees with:\n"
                + "\n".join(f"  {entry}: {report.drift[entry]}" for entry in new_drift)
                + "\n\nSet `nullable=` on the field to match the column. A field claiming to be "
                "non-nullable when the column is Nullable makes the type system drop null handling "
                "it needs. If the mismatch is deliberate, add it to "
                f"{BASELINE_PATH.name} with a comment saying why."
            )
        if stale:
            problems.append(
                "These fields are listed as known drift but now agree with ClickHouse:\n"
                + "\n".join(f"  {entry}" for entry in stale)
                + f"\n\nRemove them from {BASELINE_PATH.name}."
            )

        assert not problems, "\n\n".join(problems)
