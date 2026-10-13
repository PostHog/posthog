---
paths:
  - 'products/*/backend/**'
---

**Creating a new product? Run `hogli product:bootstrap <name>` — do not hand-roll the directory.**
The scaffold emits a product that is isolated from its first commit, and `product:lint --all`
fails on a new product that is not — see "New products must be isolated" in `products/README.md`.

**Otherwise, check this product's isolation status before making changes.**
Look at the product's `package.json`: if `backend:contract-check` is listed under `scripts`,
this product is isolated.

- **Isolated:** external code (core, other products) may only import from the
  `backend/facade/` package — `api.py` for data capabilities, and capability submodules
  (`queries.py`, `tasks.py`, `temporal.py`, …) for wiring that core registers or
  dispatches on. Do not expose internal modules directly, and do not add raw
  cross-product imports — go through the target product's facade instead.
  Wiring submodules may only re-export classes that implement a core-owned base
  (`QueryRunner`, `MaxTool`, Temporal defns, `@shared_task`) and are defined under the
  product's wiring locations (`backend/hogql_queries/`, `backend/max_tools.py`,
  `backend/temporal/`, `backend/tasks/`); data and error types belong in
  `facade/contracts.py`; Django models never cross the boundary, except for the few
  `(product, class)` pairs on the frozen watched-models allowance (`MODEL_CROSSINGS`),
  whose `backend/models/` + `backend/migrations/` must stay in the contract-check inputs
  (see `products/architecture.md` § Wiring couplings).
- **Not isolated** (the product is listed in `products/isolation_baseline.txt`): boundaries
  are not enforced by CI for it yet, but prefer using existing facades when they exist rather
  than importing internals.
  A product that is neither isolated nor on that list is a new product that skipped the
  scaffold — see above.

If you need to extend what's reachable across a boundary, add a function to the relevant
facade module (or a re-export to its wiring submodule) — not a `depends_on` entry in
`tach.toml`.
Run `hogli lint:tach` to verify import boundaries are clean. It runs the two tach passes CI runs:
dependencies without test code, interfaces with it, so a test may import any product's public
surface without a `depends_on` entry but never its internals.
