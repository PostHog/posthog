"""Diff engine: compare desired state against current live schema.

Produces a list of StateDiff objects, each representing a single DDL operation
(CREATE, ALTER, DROP, recreate) with the SQL to execute, target node roles,
and dependency ordering.

The diff respects ClickHouse ecosystem rules:
- DROP MV before altering source tables
- CREATE local tables before Distributed tables
- CREATE Kafka tables before MVs
- ALTER all ecosystem tables when adding a column (sharded + writable + readable)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import TableSchema

logger = logging.getLogger("migrations")

# Sentinel value used in schema YAML to indicate the value should come from Django settings
_FROM_SETTINGS_SENTINEL = "__from_settings__"

# Map of YAML setting keys to Django settings attributes
_SETTINGS_RESOLUTION: dict[str, str] = {
    "kafka_broker_list": "KAFKA_HOSTS_FOR_CLICKHOUSE",
}


def _resolve_physical_cluster(logical_name: str) -> str:
    """Resolve a YAML logical cluster name to the physical CH cluster name.

    Uses _CLUSTER_REGISTRY from cluster.py to map logical names (e.g. 'main')
    to Django settings attrs (e.g. 'CLICKHOUSE_CLUSTER'), then reads the
    setting value. Unknown names pass through unchanged so the eventual CH
    error (CLUSTER_DOESNT_EXIST) still surfaces as the signal to fix the YAML.

    Needed because the dev stack's physical cluster is 'posthog_migrations'
    while production uses 'main' — same YAML, different CH cluster name.
    """
    from posthog.clickhouse.cluster import _CLUSTER_REGISTRY

    entry = _CLUSTER_REGISTRY.get(logical_name)
    if entry is None:
        return logical_name
    _host_attr, cluster_attr = entry
    return getattr(django_settings, cluster_attr, logical_name)


def _resolve_setting(key: str) -> str:
    """Resolve a __from_settings__ sentinel to its Django settings value."""
    attr = _SETTINGS_RESOLUTION.get(key)
    if attr:
        val = getattr(django_settings, attr, None)
        if val:
            return ",".join(val) if isinstance(val, list) else str(val)
    # Fallback for local dev — warn so misconfigured prod envs are visible
    logger.warning("Setting %s (Django attr %s) is unset, falling back to kafka:9092", key, attr or key)
    return "kafka:9092"


@dataclass
class StateDiff:
    # "create", "alter_add_column", "alter_drop_column",
    # "alter_modify_column", "drop", "recreate_mv", "recreate"
    action: str
    table: str
    detail: str
    sql: str
    node_roles: list[str]
    sharded: bool = False
    is_alter_on_replicated_table: bool = False
    depends_on: list[str] = field(default_factory=list)


# Engine tier determines creation order and helps classify table types
_ENGINE_TIER: dict[str, int] = {
    "kafka": 0,
    "mergetree": 1,
    "replacingmergetree": 1,
    "replicatedmergetree": 1,
    "replicatedreplacingmergetree": 1,
    "collapsingmergetree": 1,
    "replicatedcollapsingmergetree": 1,
    "versionedcollapsingmergetree": 1,
    "replicatedversionedcollapsingmergetree": 1,
    "summingmergetree": 1,
    "replicatedsummingmergetree": 1,
    "aggregatingmergetree": 1,
    "replicatedaggregatingmergetree": 1,
    "distributed": 2,
    "materializedview": 3,
    "dictionary": 3,
}


def _engine_tier(engine: str) -> int:
    return _ENGINE_TIER.get(engine.lower(), 1)


def _is_mergetree(engine: str) -> bool:
    return "mergetree" in engine.lower()


def _is_distributed(engine: str) -> bool:
    return engine.lower() == "distributed"


def _is_mv(engine: str) -> bool:
    return engine.lower() == "materializedview"


def _is_kafka(engine: str) -> bool:
    return engine.lower() == "kafka"


def _is_dictionary(engine: str) -> bool:
    return engine.lower() == "dictionary"


# ClickHouse normalizes toIntervalX(N) → INTERVAL N X in system.columns,
# but YAML may use either form. Map function names to interval units.
_INTERVAL_FUNCS = {
    "tointervalday": "DAY",
    "tointervalhour": "HOUR",
    "tointervalminute": "MINUTE",
    "tointervalsecond": "SECOND",
    "tointervalweek": "WEEK",
    "tointervalmonth": "MONTH",
    "tointervalyear": "YEAR",
}

_INTERVAL_RE = re.compile(r"(toInterval[A-Za-z]+)\s*\(\s*([^)]+?)\s*\)")


def _normalize_interval_funcs(s: str) -> str:
    """Convert toIntervalX(N) → INTERVAL N X for CH canonical form equivalence."""

    def _sub(m: re.Match) -> str:
        fn = m.group(1).lower()
        arg = m.group(2).strip()
        unit = _INTERVAL_FUNCS.get(fn)
        return f"INTERVAL {arg} {unit}" if unit else m.group(0)

    return _INTERVAL_RE.sub(_sub, s)


def _strip_outer_balanced_parens(s: str, start: int) -> tuple[str, bool]:
    """If s[start] is '(', find matching ')' and strip if the group is redundant.

    A paren group is redundant when it wraps an AND/OR operand — i.e. the
    character before '(' or after ')' is adjacent to AND/OR (or -> or start/end).
    Returns (possibly-modified string, whether a strip happened).
    """
    if start >= len(s) or s[start] != "(":
        return s, False
    depth = 1
    i = start + 1
    while i < len(s) and depth > 0:
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return s, False
    end = i - 1  # index of closing ')'
    inner = s[start + 1 : end]
    # Don't strip if inner is empty or if stripping would remove function-call parens
    # (function call = identifier immediately before the '(')
    if start > 0 and re.match(r"\w", s[start - 1]):
        return s, False
    s = s[:start] + inner + s[end + 1 :]
    return s, True


def _strip_redundant_parens(s: str) -> str:
    """Iteratively strip semantically-redundant parentheses in lambda bodies.

    CH wraps lambda conditions at two levels:
    1. Outer: ``-> (expr)`` → ``-> expr``
    2. Per-operand: ``(cond1) AND (cond2)`` → ``cond1 AND cond2``

    Since we only need equality comparison (not execution), stripping these
    redundant wrappers is safe.
    """
    prev = None
    while prev != s:
        prev = s
        # Strip outer parens wrapping the full lambda body: -> (...) → -> ...
        m = re.search(r"->\s*\(", s)
        if m:
            paren_start = m.end() - 1
            s, _ = _strip_outer_balanced_parens(s, paren_start)

        # Strip parens around AND/OR operands by scanning for paren groups
        # adjacent to boolean operators
        changed = True
        while changed:
            changed = False
            # Find (expr) followed by AND/OR
            for m in re.finditer(r"\(", s):
                pos = m.start()
                # Skip function-call parens (preceded by word char)
                if pos > 0 and re.match(r"\w", s[pos - 1]):
                    continue
                # Find the matching close paren
                depth = 1
                j = pos + 1
                while j < len(s) and depth > 0:
                    if s[j] == "(":
                        depth += 1
                    elif s[j] == ")":
                        depth -= 1
                    j += 1
                if depth != 0:
                    continue
                close = j - 1
                # Check if followed by AND/OR or preceded by AND/OR (or ->)
                after = s[close + 1 :].lstrip()
                before = s[:pos].rstrip()
                is_bool_context = (
                    re.match(r"\b(?:and|or)\b", after, re.IGNORECASE)
                    or re.search(r"\b(?:and|or)\s*$", before, re.IGNORECASE)
                    or before.endswith("->")
                )
                if is_bool_context:
                    inner = s[pos + 1 : close]
                    s = s[:pos] + inner + s[close + 1 :]
                    changed = True
                    break  # restart scan after mutation

        s = re.sub(r"  +", " ", s)
    return s


def _normalize_default(s: str) -> str:
    """Normalize a default expression for semantic comparison.

    Handles: backslash-escaped quotes, toIntervalX(N) → INTERVAL N X,
    case folding, whitespace collapse, lambda-body paren stripping,
    nested AND/OR operand paren stripping.
    """
    # Fix 3: Normalize backslash-escaped quotes (CH double-escapes in some contexts)
    s = s.replace('\\\\"', '"').replace('\\"', '"')
    s = _normalize_interval_funcs(s)
    s = re.sub(r"\s+", " ", s.strip().lower())
    # Fix 1+6: Strip semantically redundant parens in lambda bodies,
    # including nested per-operand parens CH adds around AND/OR clauses.
    s = _strip_redundant_parens(s)
    return s


def _normalize_type(s: str) -> str:
    """Normalize a column type string for semantic comparison.

    Handles:
    - Enum8/Enum16 → Enum (strip bit-width suffix and = N value assignments)
    - DateTime64 → DateTime64(3) (3 is the default precision)
    - Decimal(18, 10) → Decimal64(10) (CH alias)
    """
    # Fix 2: Enum8('a' = 1, 'b' = 2) → Enum('a', 'b')
    s = re.sub(r"Enum(?:8|16)\(", "Enum(", s)
    s = re.sub(r"'([^']+)'\s*=\s*\d+", r"'\1'", s)
    # Fix 4: DateTime64 without precision → DateTime64(3)
    s = re.sub(r"\bDateTime64\b(?!\()", "DateTime64(3)", s)

    # Fix 4: Decimal(18, 10) → Decimal64(10) etc.
    # Decimal(P, S) where P ≤ 18 → Decimal64(S); P ≤ 9 → Decimal32(S); P ≤ 38 → Decimal128(S)
    def _decimal_alias(m: re.Match) -> str:
        p, s = int(m.group(1)), m.group(2)
        if p <= 9:
            return f"Decimal32({s})"
        elif p <= 18:
            return f"Decimal64({s})"
        elif p <= 38:
            return f"Decimal128({s})"
        return m.group(0)

    s = re.sub(r"\bDecimal\(\s*(\d+)\s*,\s*(\d+)\s*\)", _decimal_alias, s)
    return s


# Kafka virtual columns injected by ClickHouse — not declared in YAML.
_KAFKA_VIRTUAL_COLUMNS = frozenset(
    {
        "_topic",
        "_key",
        "_offset",
        "_partition",
        "_timestamp",
        "_headers",
    }
)


def _is_kafka_virtual_column(name: str) -> bool:
    return name in _KAFKA_VIRTUAL_COLUMNS or name.startswith("_headers.")


def _columns_sql(columns: list[ColumnDef]) -> str:
    parts = []
    for col in columns:
        line = f"    {col.name} {col.type}"
        if col.default_expression:
            kind = col.default_kind or "DEFAULT"
            line += f" {kind} {col.default_expression}"
        if col.codec:
            line += f" CODEC({col.codec})"
        parts.append(line)
    return ",\n".join(parts)


def _generate_create_sql(
    table: DesiredTable,
    database: str,
    cluster: str,
) -> str:
    """Generate CREATE TABLE/VIEW SQL from a DesiredTable."""
    cols = _columns_sql(table.columns)

    if _is_mv(table.engine):
        target = table.target or ""
        select = (table.select or "SELECT * FROM ???").replace("{{ database }}", database)
        return f"CREATE MATERIALIZED VIEW IF NOT EXISTS {database}.{table.name}\nTO {database}.{target}\nAS {select}"

    if _is_distributed(table.engine):
        source = table.source or ""
        sharding = table.sharding_key or "rand()"
        physical_cluster = _resolve_physical_cluster(cluster)

        # Distributed tables that wrap a system.* table (or any source table
        # whose columns should be inherited rather than redeclared) are
        # authored in the YAML with an empty `columns: []` list. Rendering an
        # empty column list as `(\n\n)` produces a syntax error; ClickHouse
        # requires either a non-empty column list or an `AS <source>` clause
        # that tells it to copy columns from the referenced table.
        #
        # When the YAML has zero columns, emit the `AS <source>` form. Source
        # resolution:
        #   - If `source` contains a dot, use it verbatim (e.g. `system.processes`).
        #   - Otherwise, qualify it with the current database.
        # The Distributed cluster args are unchanged from the normal path.
        if not table.columns:
            source_ref = source if "." in source else f"{database}.{source}"
            return (
                f"CREATE TABLE IF NOT EXISTS {database}.{table.name} AS {source_ref}\n"
                f"ENGINE = Distributed('{physical_cluster}', '{database}', '{source}', {sharding})"
            )

        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n"
            f") ENGINE = Distributed('{physical_cluster}', '{database}', '{source}', {sharding})"
        )

    if _is_kafka(table.engine):
        settings_lines = []
        if table.settings:
            for k, v in table.settings.items():
                resolved = _resolve_setting(k) if str(v) == _FROM_SETTINGS_SENTINEL else v
                settings_lines.append(f"    {k} = '{resolved}'")
        settings_block = ",\n".join(settings_lines)
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n"
            f") ENGINE = Kafka()\n"
            f"SETTINGS\n{settings_block}"
        )

    # MergeTree family.
    # Replicated* engines must be given explicit (zk_path, replica_name) args —
    # otherwise ClickHouse falls back to a default path containing a `{uuid}` macro
    # that can only be resolved inside an ON CLUSTER query or a Replicated database
    # engine. The runner sends CREATE statements directly to each host via
    # map_hosts_by_roles(), so there is no ON CLUSTER context and the macro fails:
    #   Code: 36. DB::Exception: Macro 'uuid' in engine arguments is only supported
    #   when the UUID is explicitly specified, used within an ON CLUSTER query,
    #   or when using the Replicated database engine.
    # This mirrors the pattern tracking.py uses for the tracking table itself and
    # matches the legacy PostHog ZK path convention.
    #
    # Some MergeTree variants take additional engine arguments after the
    # zk_path/replica pair:
    #   - Collapsing:         ENGINE(zk, replica, sign_col)
    #   - VersionedCollapsing: ENGINE(zk, replica, sign_col, version_col)
    #   - Replacing:          ENGINE(zk, replica, [version_col])
    #   - Summing:            ENGINE(zk, replica, [(summed_cols)])
    # We auto-detect the canonical column names (`sign`, `version`) from the
    # table's columns. The YAML always declares them explicitly (the legacy
    # migrations that seeded the YAML use the same naming).
    column_names = {c.name for c in table.columns}
    engine_name = table.engine
    engine_lower = engine_name.lower()

    def _zk_args() -> str:
        zk_path = f"/clickhouse/tables/{{shard}}/{database}/{table.name}"
        return f"'{zk_path}', '{{replica}}'"

    def _find_column(candidates: tuple[str, ...]) -> str | None:
        """Return the first candidate column name that exists in the table.

        Legacy PostHog migrations use both `sign`/`version` and `_sign`/`_version`
        naming — the underscore-prefixed form is common for internal/system
        columns. Auto-detect both so engine arg rendering works regardless of
        which convention the YAML uses.
        """
        for c in candidates:
            if c in column_names:
                return c
        return None

    if engine_name.startswith("Replicated"):
        extra_args: list[str] = []
        if "versionedcollapsing" in engine_lower:
            # sign + version required
            sign = _find_column(("sign", "_sign"))
            version = _find_column(("version", "_version"))
            if sign:
                extra_args.append(sign)
            if version:
                extra_args.append(version)
        elif "collapsing" in engine_lower:
            # sign required
            sign = _find_column(("sign", "_sign"))
            if sign:
                extra_args.append(sign)
        elif "replacing" in engine_lower:
            # version optional — include if present
            version = _find_column(("version", "_version"))
            if version:
                extra_args.append(version)
        # Summing/Aggregating without explicit columns = OK with just zk args

        if extra_args:
            engine_call = f"{engine_name}({_zk_args()}, {', '.join(extra_args)})"
        else:
            engine_call = f"{engine_name}({_zk_args()})"
    else:
        engine_call = f"{engine_name}()"

    partition = f"\nPARTITION BY {table.partition_by}" if table.partition_by else ""
    order_by = f"\nORDER BY ({', '.join(table.order_by)})" if table.order_by else ""

    return (
        f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n(\n{cols}\n) ENGINE = {engine_call}{partition}{order_by}"
    )


def _normalize_mv_select(sql: str) -> str:
    """Normalize MV SELECT SQL for semantic comparison.

    Handles the common false-positive cases that cause spurious MV recreates:
    - Indentation/whitespace changes
    - Keyword casing (CH uppercases keywords in stored SELECT)
    - Database prefix on table names (CH adds ``posthog_test.`` or ``<db>.``)
    - Trailing ``SETTINGS`` clause (CH may append engine settings)
    """
    # Remove comments
    s = re.sub(r"--[^\n]*\n", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # Strip trailing SETTINGS clause (not part of the logical query)
    s = re.sub(r"\bSETTINGS\b\s+.*$", "", s, flags=re.IGNORECASE)
    # Lowercase everything — simpler and more robust than keyword-by-keyword
    s = s.lower()
    # Strip database prefix from qualified table names: `db.table` → `table`
    # Matches `word.` before an identifier (letter/underscore start).
    s = re.sub(r"\b\w+\.\b(?=[a-z_])", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def diff_state(
    desired: DesiredState,
    current: dict[str, TableSchema],
    database: str | None = None,
    cluster: str | None = None,
) -> list[StateDiff]:
    """Compare desired state against current schema and produce a list of diffs.

    Returns StateDiff objects sorted in dependency order (drops before creates,
    local before distributed, kafka before MV).
    """
    db = database or desired.database
    cl = cluster or desired.cluster

    drops: list[StateDiff] = []
    creates: list[StateDiff] = []
    alters: list[StateDiff] = []
    recreates: list[StateDiff] = []

    # Skip Dictionary tables entirely — the desired-state YAML only declares
    # columns/engine, not the PRIMARY KEY / SOURCE / LAYOUT / LIFETIME metadata
    # that `CREATE DICTIONARY` requires. Legacy `migrate_clickhouse` creates
    # these with hand-written DDL; `ch_migrate` ignores them for now and emits
    # a warning per skipped dictionary. Revisit once the YAML schema grows
    # Dictionary-specific fields.
    skipped_dicts = [name for name, t in desired.tables.items() if _is_dictionary(t.engine)]
    if skipped_dicts:
        logger.warning(
            "ch_migrate: skipping %d Dictionary table(s) — YAML lacks SOURCE/LAYOUT/LIFETIME, "
            "use legacy migrate_clickhouse for dictionaries: %s",
            len(skipped_dicts),
            ", ".join(skipped_dicts),
        )

    # Skip MaterializedViews whose SELECT body contains a literal `...`
    # placeholder. The YAML baseline was generated mechanically from the live
    # schema for some ecosystems and left the SELECT body as a sentinel for
    # later hand-filling. Two variants observed in the wild:
    #   - `SELECT ... FROM source`             (full body stubbed)
    #   - `SELECT col1, col2, ... FROM source` (trailing cols stubbed)
    # Both render into invalid SQL. These MVs stay managed by legacy
    # `migrate_clickhouse` until the YAML grows real bodies. The trailing
    # `...` in a valid SELECT list is not legal ClickHouse syntax, so this
    # check won't accidentally skip real MVs.
    def _has_placeholder_select(t: DesiredTable) -> bool:
        if not _is_mv(t.engine) or not t.select:
            return False
        select_body = t.select
        # `SELECT ...` at the start (F11 original) or `, ...` before FROM
        # (person_query_log MVs discovered in 2026-04-11 reverify).
        return "SELECT ..." in select_body or ", ..." in select_body or ",..." in select_body

    skipped_placeholder_mvs = [name for name, t in desired.tables.items() if _has_placeholder_select(t)]
    if skipped_placeholder_mvs:
        logger.warning(
            "ch_migrate: skipping %d MV(s) with placeholder SELECT body — "
            "fill in the YAML select: field to manage these via ch_migrate: %s",
            len(skipped_placeholder_mvs),
            ", ".join(skipped_placeholder_mvs),
        )

    def _should_skip(name: str, t: DesiredTable) -> bool:
        return _is_dictionary(t.engine) or _has_placeholder_select(t)

    desired_without_skipped = {name: t for name, t in desired.tables.items() if not _should_skip(name, t)}

    desired_names = set(desired_without_skipped.keys())
    current_names = {n for n in current.keys() if not _is_dictionary(current[n].engine)}

    # Tables to drop (in current but not in desired)
    for table_name in sorted(current_names - desired_names):
        current_table = current[table_name]
        drops.append(
            StateDiff(
                action="drop",
                table=table_name,
                detail=f"Table {table_name} exists but is not in desired state",
                sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                node_roles=["ALL"],
            )
        )

    # Tables to create (in desired but not in current)
    for table_name in sorted(desired_names - current_names):
        desired_table = desired.tables[table_name]
        deps = []
        if _is_distributed(desired_table.engine) and desired_table.source:
            deps.append(desired_table.source)
        if _is_mv(desired_table.engine):
            if desired_table.target:
                deps.append(desired_table.target)

        creates.append(
            StateDiff(
                action="create",
                table=table_name,
                detail=f"Create {desired_table.engine} table {table_name}",
                sql=_generate_create_sql(desired_table, db, cl),
                node_roles=desired_table.on_nodes,
                sharded=desired_table.sharded,
                depends_on=deps,
            )
        )

    # Tables that exist in both — check for changes
    for table_name in sorted(desired_names & current_names):
        desired_table = desired.tables[table_name]
        current_table = current[table_name]

        # Engine mismatch → recreate
        if desired_table.engine.lower() != current_table.engine.lower():
            if _is_mv(desired_table.engine) or _is_mv(current_table.engine):
                recreates.append(
                    StateDiff(
                        action="recreate_mv",
                        table=table_name,
                        detail=(
                            f"Recreate MV {table_name} "
                            f"(engine changed: {current_table.engine} -> {desired_table.engine})"
                        ),
                        sql=(f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}"),
                        node_roles=desired_table.on_nodes,
                        depends_on=[desired_table.target] if desired_table.target else [],
                    )
                )
            else:
                recreates.append(
                    StateDiff(
                        action="recreate",
                        table=table_name,
                        detail=(
                            f"Recreate {table_name} (engine changed: {current_table.engine} -> {desired_table.engine})"
                        ),
                        sql=(f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}"),
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                    )
                )
            continue

        # Structural field comparisons (order_by, partition_by, sharding_key, source, target, settings)
        structural_recreate = False
        structural_details: list[str] = []

        if _is_mergetree(desired_table.engine):
            # ORDER BY
            if desired_table.order_by:
                current_sorting = current_table.sorting_key
                desired_sorting = ", ".join(desired_table.order_by)
                if current_sorting and current_sorting != desired_sorting:
                    structural_details.append(f"ORDER BY changed: {current_sorting} -> {desired_sorting}")
                    structural_recreate = True
            # PARTITION BY
            if desired_table.partition_by:
                if current_table.partition_key and current_table.partition_key != desired_table.partition_by:
                    structural_details.append(
                        f"PARTITION BY changed: {current_table.partition_key} -> {desired_table.partition_by}"
                    )
                    structural_recreate = True

        if _is_distributed(desired_table.engine):
            # sharding_key — requires recreate
            if desired_table.sharding_key and current_table.engine_full:
                if desired_table.sharding_key not in current_table.engine_full:
                    structural_details.append(f"sharding_key changed (desired: {desired_table.sharding_key})")
                    structural_recreate = True
            # source — the local table backing the Distributed table
            if desired_table.source and current_table.engine_full:
                if desired_table.source not in current_table.engine_full:
                    structural_details.append(f"source table changed (desired: {desired_table.source})")
                    structural_recreate = True

        if _is_mv(desired_table.engine):
            # target — the destination table for the MV
            if desired_table.target and current_table.engine_full:
                if desired_table.target not in current_table.engine_full:
                    structural_details.append(f"MV target changed (desired: {desired_table.target})")
                    structural_recreate = True

        if _is_kafka(desired_table.engine):
            # Kafka settings (broker_list, topic_list, group_name, format) — requires recreate
            if desired_table.settings and current_table.engine_full:
                for setting_key, setting_val in desired_table.settings.items():
                    resolved = (
                        _resolve_setting(setting_key)
                        if str(setting_val) == _FROM_SETTINGS_SENTINEL
                        else str(setting_val)
                    )
                    if resolved not in current_table.engine_full:
                        structural_details.append(f"Kafka setting '{setting_key}' changed (desired: {resolved})")
                        structural_recreate = True

        if structural_recreate:
            detail_str = "; ".join(structural_details)
            if _is_mv(desired_table.engine):
                recreates.append(
                    StateDiff(
                        action="recreate_mv",
                        table=table_name,
                        detail=f"Recreate MV {table_name} ({detail_str})",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}",
                        node_roles=desired_table.on_nodes,
                        depends_on=[desired_table.target] if desired_table.target else [],
                    )
                )
            else:
                recreates.append(
                    StateDiff(
                        action="recreate",
                        table=table_name,
                        detail=f"Recreate {table_name} ({detail_str})",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                    )
                )
            continue

        # Column default/codec changes — ALTER MODIFY COLUMN (checked during column comparison below)

        # For MVs, compare SELECT if both sides have it
        if _is_mv(desired_table.engine) and desired_table.select:
            current_select = current_table.as_select if hasattr(current_table, "as_select") else ""
            if current_select and _normalize_mv_select(current_select) != _normalize_mv_select(desired_table.select):
                drops.append(
                    StateDiff(
                        action="drop",
                        table=table_name,
                        detail=f"Drop MV {table_name} (SELECT changed — will recreate)",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                        node_roles=desired_table.on_nodes,
                    )
                )
                creates.append(
                    StateDiff(
                        action="create",
                        table=table_name,
                        detail=f"Recreate MV {table_name} with updated SELECT",
                        sql=_generate_create_sql(desired_table, db, cl),
                        node_roles=desired_table.on_nodes,
                    )
                )
            elif not current_select:
                import logging

                logging.getLogger("migrations").warning(
                    "MV %s: SELECT comparison not possible (as_select not available from host). "
                    "Verify manually with 'ch_migrate schema'.",
                    table_name,
                )

        # Column comparison
        desired_cols = {c.name: c for c in desired_table.columns}
        current_cols = {c.name: c for c in current_table.columns}

        # Distributed tables with empty columns inherit from their source table —
        # skip column diff entirely to avoid spurious DROP COLUMN diffs.
        if _is_distributed(desired_table.engine) and not desired_table.columns:
            continue

        # Filter Kafka virtual columns from live schema — CH injects these
        # automatically (_topic, _key, _offset, etc.) and they aren't in YAML.
        if _is_kafka(desired_table.engine):
            current_cols = {k: v for k, v in current_cols.items() if not _is_kafka_virtual_column(k)}

        # Kafka/Dictionary engines don't support ALTER — recreate instead.
        # Compare by (name, type) tuples because desired_cols has ColumnDef values
        # while current_cols has ColumnSchema values (different dataclass types).
        if desired_table.engine.lower() in ("kafka", "dictionary") and (
            {(c.name, _normalize_type(c.type)) for c in desired_cols.values()}
            != {(c.name, _normalize_type(c.type)) for c in current_cols.values()}
        ):
            drops.append(
                StateDiff(
                    action="drop",
                    table=table_name,
                    detail=f"Drop {desired_table.engine} table {table_name} (recreate for column change)",
                    sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                    node_roles=desired_table.on_nodes,
                )
            )
            creates.append(
                StateDiff(
                    action="create",
                    table=table_name,
                    detail=f"Recreate {desired_table.engine} table {table_name} with updated columns",
                    sql=_generate_create_sql(desired_table, db, cl),
                    node_roles=desired_table.on_nodes,
                )
            )
            continue

        # Skip column diffing for MVs (columns are derived from SELECT)
        if _is_mv(desired_table.engine):
            continue

        is_replicated = _is_mergetree(desired_table.engine) and "replicated" in desired_table.engine.lower()

        # Missing columns (in desired but not in current) → ADD COLUMN
        for col_name in sorted(set(desired_cols.keys()) - set(current_cols.keys())):
            col = desired_cols[col_name]
            default_clause = ""
            if col.default_expression:
                kind = col.default_kind or "DEFAULT"
                default_clause = f" {kind} {col.default_expression}"
            alters.append(
                StateDiff(
                    action="alter_add_column",
                    table=table_name,
                    detail=f"Add column {col_name} {col.type} to {table_name}",
                    sql=f"ALTER TABLE {db}.{table_name} ADD COLUMN IF NOT EXISTS {col_name} {col.type}{default_clause}",
                    node_roles=desired_table.on_nodes,
                    sharded=desired_table.sharded,
                    is_alter_on_replicated_table=is_replicated,
                )
            )

        # Extra columns (in current but not in desired) → DROP COLUMN
        for col_name in sorted(set(current_cols.keys()) - set(desired_cols.keys())):
            alters.append(
                StateDiff(
                    action="alter_drop_column",
                    table=table_name,
                    detail=f"Drop column {col_name} from {table_name}",
                    sql=f"ALTER TABLE {db}.{table_name} DROP COLUMN IF EXISTS {col_name}",
                    node_roles=desired_table.on_nodes,
                    sharded=desired_table.sharded,
                    is_alter_on_replicated_table=is_replicated,
                )
            )

        # Type mismatches → MODIFY COLUMN
        for col_name in sorted(set(desired_cols.keys()) & set(current_cols.keys())):
            desired_col = desired_cols[col_name]
            current_col = current_cols[col_name]
            if _normalize_type(desired_col.type) != _normalize_type(current_col.type):
                alters.append(
                    StateDiff(
                        action="alter_modify_column",
                        table=table_name,
                        detail=(
                            f"Modify column {col_name} from {current_col.type} to {desired_col.type} on {table_name}"
                        ),
                        sql=f"ALTER TABLE {db}.{table_name} MODIFY COLUMN {col_name} {desired_col.type}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                        is_alter_on_replicated_table=is_replicated,
                    )
                )
                continue

            # Default kind/expression changes → MODIFY COLUMN.
            # Normalize semantically: CH lowercases function names in system.columns
            # and converts toIntervalX(N) to INTERVAL N X. See _normalize_default().
            desired_default = f"{desired_col.default_kind} {desired_col.default_expression}".strip()
            current_default = f"{current_col.default_kind} {current_col.default_expression}".strip()

            if desired_default and _normalize_default(desired_default) != _normalize_default(current_default):
                kind = desired_col.default_kind or "DEFAULT"
                modify_clause = f"{col_name} {desired_col.type} {kind} {desired_col.default_expression}"
                alters.append(
                    StateDiff(
                        action="alter_modify_column",
                        table=table_name,
                        detail=(
                            f"Modify column {col_name} default on {table_name}: "
                            f"{current_default!r} -> {desired_default!r}"
                        ),
                        sql=f"ALTER TABLE {db}.{table_name} MODIFY COLUMN {modify_clause}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                        is_alter_on_replicated_table=is_replicated,
                    )
                )

    # Sort by dependency order:
    # 1. Drop MVs first (tier 3 drops first)
    # 2. Drop distributed (tier 2)
    # 3. Drop local/kafka (tier 1/0)
    # 4. Alters on local tables
    # 5. Alters on distributed tables
    # 6. Creates in tier order (kafka=0, local=1, distributed=2, MV=3)
    # 7. Recreates (MV recreates last)

    def _drop_sort_key(d: StateDiff) -> tuple[int, str]:
        # Higher tier drops first (MVs before distributed before local)
        tier = 3 - _engine_tier(current.get(d.table, TableSchema(name=d.table, engine="")).engine)
        return (tier, d.table)

    def _alter_sort_key(d: StateDiff) -> tuple[int, str]:
        table = desired.tables.get(d.table)
        tier = _engine_tier(table.engine) if table else 1
        return (tier, d.table)

    def _create_sort_key(d: StateDiff) -> tuple[int, str]:
        table = desired.tables.get(d.table)
        tier = _engine_tier(table.engine) if table else 1
        return (tier, d.table)

    drops.sort(key=_drop_sort_key)
    alters.sort(key=_alter_sort_key)
    creates.sort(key=_create_sort_key)

    # Fix 5: Kafka/MV recreate cascade prevention.
    # When an MV is recreated (DROP + CREATE), ClickHouse can cascade-drop
    # the source Kafka table if it was created inline. Re-add a CREATE step
    # for any Kafka table that is the source of a recreated MV.
    kafka_tables_in_desired = {name: t for name, t in desired_without_skipped.items() if _is_kafka(t.engine)}
    if kafka_tables_in_desired:
        # Collect table names already being created
        tables_being_created = {d.table for d in creates}
        for rec in recreates:
            if rec.action != "recreate_mv":
                continue
            mv_table = desired_without_skipped.get(rec.table)
            if not mv_table or not mv_table.select:
                continue
            # Find which Kafka tables are referenced in the MV SELECT
            for kafka_name, kafka_def in kafka_tables_in_desired.items():
                # Check if the Kafka table name appears in the MV's SELECT
                # (qualified as db.name or unqualified)
                if kafka_name in mv_table.select and kafka_name not in tables_being_created:
                    creates.append(
                        StateDiff(
                            action="create",
                            table=kafka_name,
                            detail=f"Re-create Kafka table {kafka_name} (cascade-dropped by MV {rec.table} recreate)",
                            sql=_generate_create_sql(kafka_def, db, cl),
                            node_roles=kafka_def.on_nodes,
                            depends_on=[],
                        )
                    )
                    tables_being_created.add(kafka_name)

    return drops + alters + creates + recreates


def detect_orphans(
    desired_states: list[DesiredState],
    current: dict[str, TableSchema],
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    """Find tables in current schema that are not declared in any YAML.

    Returns a sorted list of orphan table names. This is read-only — it
    only reports, it does not drop anything.
    """
    declared: set[str] = set()
    for ds in desired_states:
        declared.update(ds.tables.keys())

    default_exclude = {"infi_clickhouse_orm_migrations", "clickhouse_schema_migrations"}
    exclude = default_exclude | set(exclude_patterns or [])

    orphans = []
    for name in current:
        if name in declared or name in exclude:
            continue
        engine = current[name].engine.lower()
        if engine in ("view", "join"):
            continue
        if name.startswith("_tmp") or name.startswith("pending_deletes"):
            continue
        orphans.append(name)

    return sorted(orphans)
