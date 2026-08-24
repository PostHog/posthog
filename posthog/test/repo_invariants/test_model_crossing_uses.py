"""Two-way ratchet on disallowed uses of watched-models crossing classes.

A model class listed in MODEL_CROSSINGS may leave its product, but consumer code may only use it in
the instance-free shapes `hogli product:crossings` recognizes. Every other use is disallowed and
frozen here, so the count can fall but never rise.

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
        "A '+' line is a new disallowed use of a crossing model class. Counts may only go down, so "
        "change the caller: move the query, serializer or write into the model's own product and "
        "call a facade function instead. Only a doctrine amendment in products/architecture.md "
        "§ Wiring couplings can add a line.\n"
        f"A '-' line means a use went away — good, but the file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )
