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
]

_CHILD = f"""
import importlib
for mod in {DJANGO_FREE_MODULES!r}:
    importlib.import_module(mod)
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
assert isinstance(parse_select("select 1"), ast.SelectQuery)
assert isinstance(parse_expr("1 + 1"), ast.Expr)
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
