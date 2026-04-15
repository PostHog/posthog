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

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredTable

logger = logging.getLogger("migrations")

# Sentinel value used in schema YAML to indicate the value should come from Django settings
_FROM_SETTINGS_SENTINEL = "__from_settings__"

# Map of YAML setting keys to Django settings attributes
_SETTINGS_RESOLUTION: dict[str, str] = {
    "kafka_broker_list": "KAFKA_HOSTS_FOR_CLICKHOUSE",
    "password": "CLICKHOUSE_PASSWORD",
    "user": "CLICKHOUSE_USER",
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
    """Resolve a __from_settings__ sentinel to its Django settings value.

    Each key resolves independently. Only `kafka_broker_list` falls back to the
    dev-stack broker host — credentials (`password`, `user`) return an empty
    string when unset, which renders as an empty SOURCE/LAYOUT param. Prior
    behavior returned `kafka:9092` for every unset key, corrupting non-Kafka
    rendered DDL like `PASSWORD 'kafka:9092'` for Dictionary sources.
    """
    attr = _SETTINGS_RESOLUTION.get(key)
    if attr:
        val = getattr(django_settings, attr, None)
        if val:
            return ",".join(val) if isinstance(val, list) else str(val)
    if key == "kafka_broker_list":
        logger.warning("Setting %s (Django attr %s) is unset, falling back to kafka:9092", key, attr or key)
        return "kafka:9092"
    logger.warning("Setting %s (Django attr %s) is unset, returning empty string", key, attr or key)
    return ""


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
    # Logical cluster this diff targets (e.g. "main", "logs", "sessions").
    # Set by _compute_diffs so handle_apply can route each step to the right
    # cluster instead of running everything against the migrations cluster.
    cluster: str = ""


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


def _drop_stmt(engine: str, database: str, table: str) -> str:
    """Return the right DROP verb for an engine. Dictionaries require DROP DICTIONARY."""
    if _is_dictionary(engine):
        return f"DROP DICTIONARY IF EXISTS {database}.{table}"
    return f"DROP TABLE IF EXISTS {database}.{table}"


# Tracking tables are bookkeeping infrastructure managed by `bootstrap`,
# never declared in any YAML. Both `diff_state` and the cluster-wide orphan
# scan in `_compute_diffs` exclude them so we never emit a DROP for the
# tool's own state tables.
TRACKING_TABLES: frozenset[str] = frozenset(
    {
        "clickhouse_schema_migrations",
        "infi_clickhouse_orm_migrations",
        "infi_clickhouse_orm_migrations_distributed",
    }
)


def has_placeholder_select(t: DesiredTable) -> bool:
    """True if a desired MV's SELECT body contains a `...` placeholder.

    The YAML baseline for several ecosystems was mechanically generated and
    left the SELECT body as a sentinel for later hand-filling. These MVs
    stay managed by legacy `migrate_clickhouse` until the YAML grows real
    bodies. Two variants observed in the wild:
      - `SELECT ... FROM source`             (full body stubbed)
      - `SELECT col1, col2, ... FROM source` (trailing cols stubbed)
    The trailing `...` in a valid SELECT list is not legal ClickHouse
    syntax, so this check won't accidentally skip real MVs.
    """
    if not _is_mv(t.engine) or not t.select:
        return False
    select_body = t.select
    return "SELECT ..." in select_body or ", ..." in select_body or ",..." in select_body


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
    # Bool and Boolean are aliases in ClickHouse — normalize to Boolean
    s = re.sub(r"\bBool\b", "Boolean", s)
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


# Dictionary metadata renderers. Keep these as small, pure functions so the
# DROP+CREATE path below can re-use them without duplicating format strings.
# Value types: YAML admits str/int/bool for source+layout params.


def _normalize_layout_type(layout: str) -> str:
    """Normalize a dictionary LAYOUT type name for semantic comparison.

    CH auto-prepends COMPLEX_KEY_ when the primary key is non-integer or
    composite. HASHED with String key → COMPLEX_KEY_HASHED. RANGE_HASHED with
    String key → COMPLEX_KEY_RANGE_HASHED. These are semantically identical
    — the YAML declares HASHED but CH stores COMPLEX_KEY_HASHED. Strip the
    prefix to compare.

    The two introspection sources (`layout_name` column vs `LAYOUT(...)` clause
    parsed out of `create_table_query`) disagree on underscores — one stores
    `COMPLEX_KEY_RANGE_HASHED`, the other `COMPLEXKEYRANGEHASHED`. Strip all
    underscores after the prefix strip so both forms compare equal regardless
    of which introspection path produced the string.
    """
    upper = layout.upper()
    upper = re.sub(r"^COMPLEX_KEY_", "", upper)
    upper = re.sub(r"^COMPLEXKEY", "", upper)
    return upper.replace("_", "")


def _render_dict_param(key: str, value: object) -> str:
    """Render one `key value` pair inside a SOURCE(...) or LAYOUT(...) clause.

    Handles the `__from_settings__` sentinel — when set, resolves via Django
    settings using the YAML key (matching the Kafka settings convention).
    Strings are single-quoted, ints/bools are bare.
    """
    if isinstance(value, str) and value == _FROM_SETTINGS_SENTINEL:
        return f"{key} '{_resolve_setting(key)}'"
    if isinstance(value, str):
        return f"{key} '{value}'"
    if isinstance(value, bool):
        return f"{key} {1 if value else 0}"
    return f"{key} {value}"


def _render_dict_source(source: dict | None) -> str:
    """Render SOURCE(...) clause from a YAML mapping.

    `type` is the source kind (CLICKHOUSE, HTTP, MYSQL, etc). All other keys
    become parameter names inside the parens. Example:
        {"type": "HTTP", "url": "https://x", "format": "CSVWithNames"}
      → SOURCE(HTTP(url 'https://x' format 'CSVWithNames'))
    """
    if not source or "type" not in source:
        raise ValueError("Dictionary source requires a 'type' key (e.g. CLICKHOUSE, HTTP)")
    kind = source["type"].upper()
    parts = [_render_dict_param(k, v) for k, v in source.items() if k != "type"]
    inner = " ".join(parts)
    return f"SOURCE({kind}({inner}))"


def _render_dict_layout(layout: dict | None) -> str:
    """Render LAYOUT(TYPE(...)) clause. Optional `params` becomes key/value pairs."""
    if not layout or "type" not in layout:
        raise ValueError("Dictionary layout requires a 'type' key (e.g. HASHED, COMPLEX_KEY_HASHED)")
    kind = layout["type"].upper()
    params = layout.get("params") or {}
    if params:
        inner = " ".join(_render_dict_param(k, v) for k, v in params.items())
        return f"LAYOUT({kind}({inner}))"
    return f"LAYOUT({kind}())"


def _render_dict_lifetime(lifetime: dict | None) -> str:
    """Render LIFETIME(MIN x MAX y). Both min+max required for stable refresh windows."""
    if not lifetime or "min" not in lifetime or "max" not in lifetime:
        raise ValueError("Dictionary lifetime requires 'min' and 'max' keys")
    return f"LIFETIME(MIN {int(lifetime['min'])} MAX {int(lifetime['max'])})"


def _render_dict_range(dict_range: dict | None) -> str:
    """Render RANGE(MIN x MAX y). Used by RANGE_HASHED layouts for per-range lookups.

    `min`/`max` are column names (e.g. `start_date`/`end_date`), not integer
    bounds — CH interprets them as column refs into the dictionary's own rows.
    Returns an empty string when `dict_range` is None (non-RANGE_HASHED dicts).
    """
    if not dict_range:
        return ""
    if "min" not in dict_range or "max" not in dict_range:
        raise ValueError("Dictionary range requires 'min' and 'max' keys (column names)")
    return f"RANGE(MIN {dict_range['min']} MAX {dict_range['max']})"


def _generate_create_sql(
    table: DesiredTable,
    database: str,
    cluster: str,
) -> str:
    """Generate CREATE TABLE/VIEW SQL from a DesiredTable."""
    cols = _columns_sql(table.columns)

    if _is_dictionary(table.engine):
        if not table.primary_key:
            raise ValueError(f"Dictionary {table.name!r} missing required 'primary_key'")
        pk = f"PRIMARY KEY {table.primary_key}"
        source = _render_dict_source(table.dict_source)
        layout = _render_dict_layout(table.dict_layout)
        lifetime = _render_dict_lifetime(table.dict_lifetime)
        rng = _render_dict_range(table.dict_range)
        # RANGE clause appears after LIFETIME in the DDL grammar. Only RANGE_HASHED
        # layouts use it — for other layouts, _render_dict_range returns "" and we
        # omit the extra line entirely.
        tail = f"\n{rng}" if rng else ""
        return (
            f"CREATE DICTIONARY IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n)\n"
            f"{pk}\n{source}\n{layout}\n{lifetime}{tail}"
        )

    if _is_mv(table.engine):
        target = table.target or ""
        select = (table.select or "SELECT * FROM ???").replace("{{ database }}", database)
        return f"CREATE MATERIALIZED VIEW IF NOT EXISTS {database}.{table.name}\nTO {database}.{target}\nAS {select}"

    if _is_distributed(table.engine):
        source = table.source or ""
        sharding = table.sharding_key or "rand()"
        physical_cluster = _resolve_physical_cluster(cluster)

        # Split `source` into database + table arguments for the Distributed
        # engine. When the YAML says `source: system.processes`, passing the
        # whole string as the table-name argument causes ClickHouse to resolve
        # `system.processes` as a table in the local database, which fails.
        # Splitting on the first `.` lets the engine find the source in a
        # different database (e.g. `system.*` or a shared data DB).
        if "." in source:
            src_db, src_table = source.split(".", 1)
        else:
            src_db = database
            src_table = source

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
        # The Distributed cluster args use the split src_db/src_table.
        if not table.columns:
            source_ref = source if "." in source else f"{database}.{source}"
            return (
                f"CREATE TABLE IF NOT EXISTS {database}.{table.name} AS {source_ref}\n"
                f"ENGINE = Distributed('{physical_cluster}', '{src_db}', '{src_table}', {sharding})"
            )

        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n"
            f") ENGINE = Distributed('{physical_cluster}', '{src_db}', '{src_table}', {sharding})"
        )

    if _is_kafka(table.engine):
        # Kafka engine doesn't support MATERIALIZED or EPHEMERAL columns — they
        # get silently dropped on CREATE, causing MVs above to fail when their
        # SELECT references the missing columns. Strip them from the column list.
        kafka_cols = [c for c in table.columns if not c.default_kind or c.default_kind.upper() in ("DEFAULT", "")]
        kafka_cols_sql = _columns_sql(kafka_cols)
        settings_lines = []
        if table.settings:
            for k, v in table.settings.items():
                resolved = _resolve_setting(k) if str(v) == _FROM_SETTINGS_SENTINEL else v
                settings_lines.append(f"    {k} = '{resolved}'")
        settings_block = ",\n".join(settings_lines)
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{kafka_cols_sql}\n"
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


def _strip_trailing_settings(s: str) -> str:
    """Remove a top-level trailing ``SETTINGS ...`` clause.

    Scans for ``SETTINGS`` tokens from right to left and strips the first one
    that sits at paren-depth 0. Tokens inside subqueries (positive depth)
    are left alone — those aren't the MV's engine settings, they're part of
    the SELECT's semantics.
    """
    positions = [m.start() for m in re.finditer(r"\bSETTINGS\b", s, re.IGNORECASE)]
    for pos in reversed(positions):
        depth = 0
        for ch in s[:pos]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        if depth == 0:
            return s[:pos].rstrip()
    return s


def _normalize_mv_select(sql: str, database: str | None = None) -> str:
    """Normalize MV SELECT SQL for semantic comparison.

    Handles the common false-positive cases that cause spurious MV recreates:
    - Indentation/whitespace changes
    - Keyword casing (CH uppercases keywords in stored SELECT)
    - Database prefix on table names (CH adds ``posthog_test.`` or ``<db>.``)
    - Trailing ``SETTINGS`` clause (CH may append engine settings)

    ``database`` scopes the database-prefix strip: only ``<database>.`` is
    removed, so table aliases in JOINs (e.g. ``a.x, b.y``) survive. When
    ``None``, the legacy Jinja ``{{ database }}.`` template is still stripped.
    """
    # Remove comments
    s = re.sub(r"--[^\n]*\n", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # Strip top-level trailing SETTINGS clause (subquery SETTINGS survive)
    s = _strip_trailing_settings(s)
    # Resolve Jinja-style {{ database }} template before lowercasing
    s = re.sub(r"\{\{\s*database\s*\}\}\.", "", s)
    # Lowercase everything — simpler and more robust than keyword-by-keyword
    s = s.lower()
    # Strip the configured database prefix only (not JOIN aliases). If the
    # caller didn't supply one, leave all ``word.`` prefixes intact.
    if database:
        s = re.sub(rf"\b{re.escape(database.lower())}\.", "", s)
    # Normalize == to = with surrounding spaces (CH stores `x = 0`, YAML may have `x==0`)
    s = re.sub(r"==", " = ", s)
    # Strip redundant parens that CH adds to lambda bodies and expressions
    s = _strip_redundant_parens(s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()
