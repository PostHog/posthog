import os
import sys
import subprocess

# The HogQL parser and AST layer must import and run without django.setup() — no Django ORM
# or app-model coupling. That is what lets these modules (and the corpus/fuzzing scripts built
# on them) run standalone in workers, CLIs, and tooling without paying the Django startup tax.
# If someone adds a `from posthog.models import ...` (or any ORM import) into one of these,
# importing it in a fresh interpreter raises AppRegistryNotReady and this test fails.
DJANGO_FREE_MODULES = [
    "posthog.uuidt",
    "posthog.exchange_rate_constants",
    "posthog.raw_sessions_v3_ad_ids",
    "posthog.clickhouse.events_json",
    "posthog.property_columns",
    "posthog.week_start_day",
    "products.event_definitions.backend.property_type",
    "posthog.hogql.ast",
    "posthog.hogql.base",
    "posthog.hogql.visitor",
    "posthog.hogql.errors",
    "posthog.hogql.timings",
    "posthog.hogql.placeholders",
    "posthog.hogql.escape_sql",
    "posthog.hogql.functions.mapping",
    "posthog.hogql.database.models",
    "posthog.hogql.parser",
    # database.database transitively imports every schema table module, so importing it here
    # guards the whole schema layer; the resolver is the headline Seam 0 win (parse -> resolve
    # -> AST with no django.setup()).
    "posthog.hogql.database.database",
    "posthog.hogql.resolver",
    "posthog.hogql.property_metadata",
    "posthog.clickhouse.materialized_column_types",
    "posthog.hogql.property_planner",
    "posthog.hogql.transforms.property_types",
    "posthog.hogql.transforms.lazy_tables",
    "posthog.hogql.transforms.in_cohort",
    # clickhouse_property_resolution before printer, deliberately in the cold-start order that used
    # to deadlock: cpr pulls in printer.base/printer.clickhouse (triggering the package init), and
    # printer/utils defers its cpr import to the call site precisely so this standalone import works.
    # The printer package init imports every dialect printer plus utils, so that one import then
    # guards the whole printer layer.
    "posthog.hogql.transforms.clickhouse_property_resolution",
    "posthog.hogql.printer",
]

_CHILD = f"""
import importlib
for mod in {DJANGO_FREE_MODULES!r}:
    importlib.import_module(mod)
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.database.database import Database
assert isinstance(parse_select("select 1"), ast.SelectQuery)
assert isinstance(parse_expr("1 + 1"), ast.Expr)
# The static table catalog builds without Django — no team, no ORM.
assert Database(include_posthog_tables=True).has_table("events")

# End-to-end compile: parse -> resolve -> prepare -> print to ClickHouse SQL, with every
# Django-side load either pre-seeded on the context or stubbed at its declared boundary.
# Anything on the compile path that reaches the ORM outside those boundaries crashes here.
from unittest.mock import patch
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_metadata import PropertyMetadata

context = HogQLContext(team_id=1, enable_select_queries=True)
context.database = Database(include_posthog_tables=True)  # else Database.create_for hits the ORM
context.restricted_properties = set()  # else the access-control load hits the ORM
context.use_new_events_schema = False  # else the lazy instance-setting read hits the ORM
context.apply_events_retention_floor = False  # backend opt-out; else the retention load hits the ORM
# The unaliased count() exercises the resolver's lazy printer import for implicit-alias derivation.
node = parse_select("select count() from events where properties.$browser = 'Chrome'")
with patch(
    "posthog.hogql.transforms.property_types.load_property_metadata", return_value=PropertyMetadata()
):
    sql, _ = prepare_and_print_ast(node, context, "clickhouse")
assert sql and "FROM events" in sql, sql
assert "count()" in sql, sql
assert any(v == "Chrome" for v in context.values.values()), context.values
print("DJANGO_FREE_OK")
"""


def test_hogql_parser_and_ast_import_without_django() -> None:
    # Fresh interpreter, no django.setup(), and DJANGO_SETTINGS_MODULE stripped so we also
    # exercise the parser's settings-free fallback. Any Django-app/ORM import surfaces as
    # AppRegistryNotReady in the child.
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0 and "DJANGO_FREE_OK" in proc.stdout, (
        "HogQL parser/AST layer no longer imports without django.setup().\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "AppRegistryNotReady" not in proc.stderr, proc.stderr
