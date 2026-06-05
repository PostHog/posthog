"""Characterization corpus for HogQL property handling across the four SQL dialects.

This module is the single, importable source of truth for the property-handling regression net that gates the
printer/property-lowering rearchitecture (see ``posthog/hogql/PRINTER_REARCHITECTURE.md``). It is consumed by:

- the golden harness (``test_property_golden.py``) — compiles every logical case across the dialects it supports and
  asserts the printed SQL against a harness-owned golden file (NOT ``.ambr`` — CI owns those, see doc §8.9);
- the logical-lowering tests — assert the corpus lowers byte-identically and leaves no blob PropertyType for the printer;
- the ClickHouse execution + skip-index net — drives the physical-optimization scenarios.

Two kinds of case, matching the two axes the rearchitecture separates (doc §4.1):

- ``LOGICAL`` cases exercise *logical access* — what a property read means (JSON blob extract, struct/array access,
  is-set, deep chains, access control). Logical access is dialect-independent, so these run on every dialect that can
  represent them and their printed SQL is text-stable: it is the part of the output that must NOT churn as physical
  optimization moves out of the printer. They are the golden corpus.
- ``PHYSICAL`` scenarios exercise *physical optimization* — materialized columns, dmat, property groups, skip-index
  comparison rewrites, ``$session_id`` / ``$ai_*``. These are ClickHouse-only, require DB state (a materialized column
  must exist for the printer to use it), and their SQL text is result-equivalent but not byte-stable. The gate for
  these is execution results + skip-index ``EXPLAIN`` (doc §9.4), not golden text; they live in the execution net.
"""

from dataclasses import dataclass, field

from posthog.schema import HogQLQueryModifiers, PropertyGroupsMode

from posthog.hogql.constants import HogQLDialect

# The four dialects, in a fixed order so golden files and sweep reports are deterministic.
ALL_DIALECTS: tuple[HogQLDialect, ...] = ("hogql", "clickhouse", "postgres", "duckdb")

# ClickHouse is the only backend with materialized columns / skip indexes / property groups, and the only one that
# resolves the person-override join used by ``SELECT *`` / ``person.properties`` over the events table. The warehouse
# dialects (postgres, duckdb) execute the logical JSON access only.
CLICKHOUSE_ONLY: tuple[HogQLDialect, ...] = ("clickhouse",)
# Dialects that render a logical property read without needing the person-override machinery. ``hogql`` re-prints the
# access verbatim; ``postgres``/``duckdb`` render the ``->``/``->>`` JSON operators; ``clickhouse`` renders the
# JSONExtract-over-the-blob fallback (its physical optimizations are exercised separately, in the execution net).
LOGICAL_DIALECTS: tuple[HogQLDialect, ...] = ALL_DIALECTS


@dataclass(frozen=True)
class LogicalCase:
    """A pure-print logical-access case: parse the HogQL, print it, compare the text to golden.

    Needs no ClickHouse DB state — an unmaterialized property prints as the JSON-blob extract on ClickHouse and as the
    ``->``/``->>`` operators on the warehouse dialects, which is exactly the logical baseline the migration preserves.
    """

    name: str
    sql: str
    description: str
    dialects: tuple[HogQLDialect, ...] = LOGICAL_DIALECTS
    modifiers: HogQLQueryModifiers | None = None


@dataclass(frozen=True)
class PhysicalScenario:
    """A ClickHouse physical-optimization scenario, described declaratively for the execution + skip-index net.

    These are not golden-text cases (their SQL is result-equivalent, not byte-stable). The fields name the DB state the
    net must set up (materialized columns, property-group mode) and the HogQL to run; the net asserts results and which
    skip indexes the query plan uses.
    """

    name: str
    sql: str
    description: str
    # Materialized columns to create before running: (table, property_name, table_column, is_nullable).
    materialized: tuple[tuple[str, str, str, bool], ...] = ()
    property_groups_mode: PropertyGroupsMode | None = None
    expected_skip_indexes_used: frozenset[str] = field(default_factory=frozenset)


# --- Logical-access corpus (the golden) ------------------------------------------------------------------------------
#
# Grouped by the scenario from the surface map (doc §9.1). Every case here is dialect-independent in *meaning*; the
# golden records how each dialect renders that meaning. ClickHouse renders the JSON-blob fallback (no materialization),
# which is the un-optimized logical baseline.

LOGICAL_CASES: tuple[LogicalCase, ...] = (
    # Simple reads and access syntax.
    LogicalCase("simple_read", "SELECT properties.foo FROM events", "single top-level property read"),
    LogicalCase("bracket_access", "SELECT properties['foo'] FROM events", "bracket index syntax, same as dot"),
    LogicalCase(
        "special_char_key",
        "SELECT properties.`weird key` FROM events",
        "property key needing identifier quoting (synthetic, never materialized — quoting is a logical concern)",
    ),
    # Deep chains and array indices.
    LogicalCase("deep_chain", "SELECT properties.a.b.c FROM events", "nested object chain a.b.c"),
    LogicalCase(
        "array_index",
        "SELECT properties.arr.1 FROM events",
        "integer chain element is an array index, passed through untyped",
    ),
    LogicalCase(
        "deep_mixed",
        "SELECT properties.obj.items.1.id FROM events",
        "mixed object/array deep chain",
    ),
    # is-set / null comparisons (logical key-existence semantics; the mat optimization must decline on these).
    LogicalCase(
        "is_null",
        "SELECT properties.foo FROM events WHERE properties.foo IS NULL",
        "IS NULL — must stay a key-existence/JSON read, never a non-nullable mat column",
    ),
    LogicalCase(
        "is_not_null",
        "SELECT properties.foo FROM events WHERE properties.foo IS NOT NULL",
        "IS NOT NULL counterpart",
    ),
    LogicalCase(
        "eq_null",
        "SELECT properties.foo FROM events WHERE properties.foo = NULL",
        "= NULL (is-not-set) — same key-existence requirement as IS NULL",
    ),
    # Comparison operators over an unmaterialized property (logical baseline = JSON read both sides).
    LogicalCase(
        "compare_eq",
        "SELECT properties.foo FROM events WHERE properties.bar = 'x'",
        "equality against a string constant",
    ),
    LogicalCase(
        "compare_neq",
        "SELECT properties.foo FROM events WHERE properties.bar != 'x'",
        "inequality",
    ),
    LogicalCase(
        "compare_in",
        "SELECT properties.foo FROM events WHERE properties.bar IN ('a', 'b')",
        "IN list",
    ),
    LogicalCase(
        "compare_not_in",
        "SELECT properties.foo FROM events WHERE properties.bar NOT IN ('a', 'b')",
        "NOT IN list",
    ),
    LogicalCase(
        "compare_range_gt",
        "SELECT properties.foo FROM events WHERE properties.bar > '5'",
        "range comparison",
    ),
    LogicalCase(
        "compare_like",
        "SELECT properties.foo FROM events WHERE properties.bar LIKE 'a%'",
        "LIKE pattern",
    ),
    LogicalCase(
        "compare_ilike",
        "SELECT properties.foo FROM events WHERE properties.bar ILIKE '%a%'",
        "case-insensitive ILIKE pattern",
    ),
    # Property used in projection positions other than WHERE (visitor-coverage characterization, doc §8.3/PR4).
    LogicalCase(
        "in_group_by",
        "SELECT properties.foo, count() FROM events GROUP BY properties.foo",
        "property in SELECT and GROUP BY",
    ),
    LogicalCase(
        "in_order_by",
        "SELECT properties.foo FROM events ORDER BY properties.foo",
        "property in ORDER BY",
    ),
    LogicalCase(
        "in_having",
        "SELECT properties.foo, count() AS c FROM events GROUP BY properties.foo HAVING properties.foo != ''",
        "property in HAVING",
    ),
    LogicalCase(
        "in_cte",
        "WITH recent AS (SELECT uuid FROM events WHERE properties.foo = 'x') SELECT uuid FROM recent",
        "property inside a CTE body — the visitor-coverage gap that the suite-wide sweep caught (doc §3.2)",
    ),
    LogicalCase(
        "in_subquery",
        "SELECT uuid FROM (SELECT uuid, properties.foo AS f FROM events) WHERE f = 'x'",
        "property inside a nested subquery",
    ),
)


# --- ClickHouse physical-optimization scenarios (the execution + skip-index net) -------------------------------------
#
# Declarative descriptions consumed by the execution net. The net creates the named materialized columns / sets the
# property-group mode, runs the HogQL, and asserts results + which skip indexes the plan uses. SQL text is NOT asserted.

PHYSICAL_SCENARIOS: tuple[PhysicalScenario, ...] = (
    PhysicalScenario(
        "mat_equals_nonnullable",
        "SELECT count() FROM events WHERE properties.test_prop = 'v'",
        "equality against a non-nullable materialized column stays index-eligible (no ifNull wrap)",
        materialized=(("events", "test_prop", "properties", False),),
    ),
    PhysicalScenario(
        "mat_equals_nullable",
        "SELECT count() FROM events WHERE properties.test_prop = 'v'",
        "equality against a nullable materialized column uses isNotNull guard, stays minmax-eligible",
        materialized=(("events", "test_prop", "properties", True),),
    ),
    PhysicalScenario(
        "mat_in",
        "SELECT count() FROM events WHERE properties.test_prop IN ('a', 'b')",
        "IN over a materialized column flips to has([...], col) to stay index-eligible",
        materialized=(("events", "test_prop", "properties", False),),
    ),
    PhysicalScenario(
        "mat_is_not_set",
        "SELECT count() FROM events WHERE properties.test_prop IS NULL",
        # §8.2 footgun. MASTER reads the scrubbed non-nullable mat column for is-set (isNull(nullIf(nullIf(col,''),
        # 'null'))), which over-matches empty-string and the literal 'null' string vs the truthful blob key-existence.
        # The rearchitecture target declines onto the blob — a *deliberate result change* for materialized is-set, not a
        # result-equivalent rewrite. The execution net locks master's current (over-matching) behavior so the flip is
        # visible and requires sign-off. See test_property_characterization.TestPhysicalScenarios.mat_is_not_set.
        "is-set over a non-nullable mat column — master over-matches (footgun); target declines onto the blob",
        materialized=(("events", "test_prop", "properties", False),),
    ),
)


def all_logical_case_names() -> list[str]:
    return [case.name for case in LOGICAL_CASES]
