"""Two-way ratchet on disallowed uses of product model classes.

A model class listed in MODEL_CROSSINGS may leave its product, but consumer code may only use it in
the instance-free shapes `hogli product:crossings` recognizes. Every other use is disallowed and
frozen here, so the count can fall but never rise.

`apps.get_model` is frozen the same way, for every product model rather than only the listed ones:
it resolves through the Django app registry, so no import linter can see the edge. Test modules stay
out of scope on that channel.

`drives(...)` lines read tests only: a test outside a product that executes a query runner in the
product's wiring location `backend/hogql_queries/`. `drives(<Kind>)` is a query kind the test builds
and runs; `drives(<Name>)` is a name it imports from there. `hogli product:lint` keeps that location
in the product's contract-check inputs while a line stands, so the isolated tests stay sound. A new
line is a new outside test that drives product code, and that test belongs in the product.

The check is strict equality, not "no worse than": a line that disappears must be deleted from the
file in the same change, so the file can never go stale behind the code.

Regenerate after removing uses:

    bin/hogli product:crossings --all --write-baseline
"""

from hogli_commands.product.crossings import BASELINE_PATH, disallowed_uses, read_baseline, scan_crossing_uses

REGENERATE = "bin/hogli product:crossings --all --write-baseline"


def test_disallowed_crossing_uses_match_the_baseline() -> None:
    scanned = sorted(use.as_baseline_line() for use in disallowed_uses(scan_crossing_uses()))
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
        "behind a facade function too. A 'drives(...)' line is a test outside the product that executes "
        "one of its query runners; move that test into the product. Only a doctrine amendment in "
        "products/architecture.md § Wiring couplings can add a line.\n"
        f"A '-' line means a use went away — good, but the file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )
