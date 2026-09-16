"""Guard: a query runner's own inputs must reach the cache key or the flight partition.

Single flight collapses concurrent blocking runs of one cache key onto one leader, and its
followers serve the entry that leader stored. An input that changes what a run computes, or the
limits it runs under, without reaching `get_cache_payload` or `single_flight_variant` therefore
lets one request be served another request's answer.

Inputs arrive two ways, and both are checked here:

  - constructor arguments beyond the base runner signature
  - class attributes with a default, which a call site can set after construction

This is a presence check, not a correctness check: it catches a runner that keys nothing, not one
whose payload forgets a field. A runner that genuinely needs neither override belongs in
ALLOWED_WITHOUT_KEYING with the reason it is safe.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
SCANNED_ROOTS = ("posthog", "ee", "products")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache", "test", "tests"}

# The base QueryRunner signature. Anything else a subclass accepts is an input of its own.
BASE_INIT_PARAMS = frozenset(
    {
        "self",
        "query",
        "team",
        "timings",
        "modifiers",
        "limit_context",
        "query_id",
        "workload",
        "extract_modifiers",
        "user",
        "ch_user",
    }
)

# Declared by the base runner classes, so a subclass repeating them states no new input.
BASE_CLASS_ATTRIBUTES = frozenset(
    {
        "query",
        "cached_response",
        "response",
        "paginator",
        "is_query_service",
        "serve_raw_cached_results",
        "raw_cached_results_bytes",
    }
)

# Either of the first two puts an input into the identity a flight pairs on. A runner that forces
# a fresh calculation never joins a flight and never serves a stored result.
KEYING_METHODS = ("get_cache_payload", "single_flight_variant", "requires_fresh_calculation")

ALLOWED_WITHOUT_KEYING = {
    "posthog/hogql_queries/ai/actors_property_taxonomy_query_runner.py::ActorsPropertyTaxonomyQueryRunner": (
        "settings is never passed by a caller, so every instance runs with the default execution settings"
    ),
    "posthog/hogql_queries/ai/event_taxonomy_query_runner.py::EventTaxonomyQueryRunner": (
        "settings is never passed by a caller, so every instance runs with the default execution settings"
    ),
    "posthog/hogql_queries/ai/team_taxonomy_query_runner.py::TeamTaxonomyQueryRunner": (
        "settings is never passed by a caller, so every instance runs with the default execution settings"
    ),
    "products/logs/backend/group_by_query_runner.py::LogsGroupByQueryRunner": (
        "the logs group-by endpoint calls calculate() directly, so these runs never read the cache or join a flight"
    ),
    "products/product_analytics/backend/hogql_queries/funnels/funnels_query_runner.py::FunnelsQueryRunner": (
        "just_summarize is never passed outside tests, so every run uses the default"
    ),
    "products/web_analytics/backend/hogql_queries/stats_table.py::WebStatsTableQueryRunner": (
        "use_v2_tables loses to the team's stored table version whenever it is set, and the caller that passes "
        "it is an accuracy check that calls calculate() directly"
    ),
    "products/web_analytics/backend/hogql_queries/web_overview.py::WebOverviewQueryRunner": (
        "use_v2_tables loses to the team's stored table version whenever it is set, and the caller that passes "
        "it is an accuracy check that calls calculate() directly"
    ),
}


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _inherits_from_runner(node: ast.ClassDef) -> bool:
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        dotted = _dotted_name(target)
        if dotted and dotted.rsplit(".", 1)[-1].endswith(("QueryRunner", "QueryRunnerMixin")):
            return True
    return False


def _constructor_inputs(node: ast.ClassDef) -> list[str]:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            args = item.args
            named = [arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            return [name for name in named if name not in BASE_INIT_PARAMS]
    return []


def _configurable_attributes(node: ast.ClassDef) -> list[str]:
    """Class attributes with a literal default: what a call site can set after construction."""
    names = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name, value = item.target.id, item.value
        elif isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            name, value = item.targets[0].id, item.value
        else:
            continue
        if not isinstance(value, ast.Constant) or name.startswith("_") or name in BASE_CLASS_ATTRIBUTES:
            continue
        # A SCREAMING_CASE name is a constant of the class, identical for every run, so it is not an
        # input. A call site that starts assigning one would get past this guard.
        if name.isupper():
            continue
        names.append(name)
    return names


def collect_runners_with_inputs() -> dict[str, list[str]]:
    """Runner classes that take inputs of their own, mapped to those inputs."""
    found: dict[str, list[str]] = {}
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts) or path.name.startswith("test_"):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "QueryRunner" not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or not _inherits_from_runner(node):
                    continue
                inputs = _constructor_inputs(node) + _configurable_attributes(node)
                if inputs:
                    key = f"{path.relative_to(REPO_ROOT).as_posix()}::{node.name}"
                    found[key] = sorted(set(inputs))
    return found


def _keys_its_inputs(key: str) -> bool:
    path, class_name = key.split("::")
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return any(isinstance(item, ast.FunctionDef) and item.name in KEYING_METHODS for item in node.body)
    return False


def test_runner_inputs_reach_the_cache_key_or_the_flight_partition() -> None:
    offenders = [
        f"{key} takes {inputs}"
        for key, inputs in sorted(collect_runners_with_inputs().items())
        if key not in ALLOWED_WITHOUT_KEYING and not _keys_its_inputs(key)
    ]
    assert not offenders, (
        "These query runners take inputs that reach neither the cache key nor the flight partition, so "
        "concurrent runs that differ only in them can be served each other's results.\n"
        "Put an input that changes the results into get_cache_payload. Put one that changes only the "
        "execution limits into single_flight_variant. If the runner is safe as it stands, add it to "
        "ALLOWED_WITHOUT_KEYING in this file with the reason.\n" + "\n".join(offenders)
    )


def test_allowlist_matches_the_runners_that_still_exist() -> None:
    detected = collect_runners_with_inputs()
    stale = sorted(key for key in ALLOWED_WITHOUT_KEYING if key not in detected)
    assert not stale, (
        "These ALLOWED_WITHOUT_KEYING entries no longer name a runner with inputs of its own. Remove them, "
        "or fix the path and class name after a move or rename.\n" + "\n".join(stale)
    )
    # A detector that stops matching would pass the guard above silently.
    assert len(detected) >= 15, f"only {len(detected)} runners with inputs detected; the scan looks broken"
