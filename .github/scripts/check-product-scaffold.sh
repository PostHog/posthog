#!/usr/bin/env bash
# Warn when a commit introduces a product directory that did not come from
# `hogli product:bootstrap`. Never blocks: the author may be mid-work, and CI
# holds the real gate (`hogli product:lint --all` against
# products/isolation_baseline.txt).
#
# Scoped to product backends that are new in this commit. Existing products are
# skipped outright, so this never has to answer "is this product isolated" — a
# question that already has one implementation, in
# tools/hogli-commands/hogli_commands/product/isolation.py, and does not need a
# second one in shell.
set -uo pipefail

BASELINE=products/isolation_baseline.txt

# Keyed on backend/, not on the product directory. Several directories under
# products/ hold only skills or scripts and are not Django products at all, and a
# frontend-only product has nothing to isolate. Keying on the backend also keeps
# the warning working when the backend arrives in a later commit than the
# directory it lands in.
new_backends=$(
    git diff --cached --name-only --diff-filter=A \
        | sed -n 's|^products/\([^/.][^/]*\)/backend/.*|\1|p' \
        | sort -u
)

for product in $new_backends; do
    # Backend already tracked, so this commit is not introducing it.
    git rev-parse -q --verify "HEAD:products/$product/backend" >/dev/null 2>&1 && continue
    # Scaffolded: bootstrap always writes turbo.json with narrowed inputs.
    [ -f "products/$product/turbo.json" ] && continue
    # Signed onto the baseline in this same commit, so devex has reviewed it.
    [ -f "$BASELINE" ] && grep -qx "$product" "$BASELINE" && continue

    printf "\n\033[33mWarning: products/%s is a new product that did not come from the scaffold.\n" "$product"
    printf "  Run: hogli product:bootstrap %s\n" "$product"
    printf "  The scaffold produces a product that is isolated from its first commit, so its\n"
    printf "  changes skip the full Django backend suite. A hand-rolled product fails\n"
    printf "  'hogli product:lint --all' unless devex lists it in %s.\033[0m\n\n" "$BASELINE"
done
