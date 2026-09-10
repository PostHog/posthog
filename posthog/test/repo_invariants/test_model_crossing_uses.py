"""Two-way ratchet on disallowed uses of product model classes.

A model class listed in MODEL_CROSSINGS may leave its product, but consumer code may only use it in
the instance-free shapes `hogli product:crossings` recognizes. Every other use is disallowed and
frozen here, so the count can fall but never rise.

`apps.get_model` is frozen the same way, for every product model rather than only the listed ones:
it resolves through the Django app registry, so no import linter can see the edge. Test modules stay
out of scope on that channel.

`reverse-accessor(...)` lines come from the model graph, not the AST: a relation field that
crosses a product boundary without `related_name="+"` adds a reverse accessor to the target class,
with no import for any other check to see. Seal the relation and delete the line in the same change;
a caller that needs reverse access gets a facade read function.

`drives(...)` lines read tests only: a test outside a product that executes a query runner in the
product's wiring location `backend/hogql_queries/`. `drives(<Kind>)` is a query kind the test builds
and runs; `drives(<Name>)` is a name it imports from there. `hogli product:lint` keeps that location
in the product's contract-check inputs while a line stands, so the isolated tests stay sound. A new
line is a new outside test that drives product code, and that test belongs in the product.

A product may watch one subtree of that location instead of the whole of it, once every other
subtree has no line left. The second test below holds that scope: it fails when a line names
something outside the watched subtree, because the watch would then miss the code the line drives.

The check is strict equality, not "no worse than": a line that disappears must be deleted from the
file in the same change, so the file can never go stale behind the code.

Regenerate after removing uses:

    bin/hogli product:crossings --all --write-baseline
"""

from hogli_commands.product.crossings import (
    BASELINE_PATH,
    all_crossing_uses,
    disallowed_uses,
    names_defined_in,
    read_baseline,
    wiring_location_label,
)

REGENERATE = "bin/hogli product:crossings --all --write-baseline"


def test_disallowed_crossing_uses_match_the_baseline() -> None:
    scanned = sorted(use.as_baseline_line() for use in disallowed_uses(all_crossing_uses()))
    recorded = sorted(read_baseline())
    if scanned == recorded:
        return

    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    raise AssertionError(
        f"{BASELINE_PATH.name} no longer matches the repo.\n"
        "A '+' line is a new disallowed use of a product model class. Counts may only go down, so "
        "change the caller: move the query, serializer or write into the model's own product and "
        "call a facade function instead. A 'get_model' line is an apps.get_model reference from "
        "outside the owning product; it is a coupling the import linters cannot see, and it belongs "
        "behind a facade function too. A 'reverse-accessor(...)' line is a boundary-crossing relation "
        'field without related_name="+" (a query:<name> row means an explicit related_query_name '
        "keeps filter() traversal alive); seal it, remove the explicit query name, and give "
        "callers a facade read function. "
        "A 'drives(...)' line is a test outside the product that executes "
        "one of its query runners; move that test into the product. Only a doctrine amendment in "
        "products/architecture.md § Wiring couplings can add a line.\n"
        f"A '-' line means a use went away — good, but the file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


# product_analytics watches backend/hogql_queries/trends/ alone, because trends is the only subtree
# tests outside the product still drive. These are the query kinds whose dispatch reaches it. Do not
# extend this set to release a line for another subtree: widen the inputs in
# products/product_analytics/turbo.json instead, or the suite stops re-running on a change the line
# says it must cover.
TRENDS_KINDS = frozenset({"TrendsQuery", "CalendarHeatmapQuery"})
WATCHED_SUBTREE = "backend/hogql_queries/trends/"


def test_product_analytics_drives_only_the_watched_subtree() -> None:
    label = wiring_location_label("product_analytics", "backend/hogql_queries/")
    watched = {f"drives({name})" for name in TRENDS_KINDS | names_defined_in("product_analytics", WATCHED_SUBTREE)}
    outside = sorted(
        line for line in read_baseline() if line.startswith(f"{label} ") and line.split()[2] not in watched
    )
    assert not outside, (
        f"{BASELINE_PATH.name} has drives lines for product_analytics that name code outside "
        f"{WATCHED_SUBTREE}, which is the only subtree products/product_analytics/turbo.json watches. "
        "A change to the subtree the line names would skip the Django suite. Either move the driving "
        "test into the product, or widen the contract-check inputs to backend/hogql_queries/**.\n"
        + "\n".join(f"  {line}" for line in outside)
    )
