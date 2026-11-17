---
paths:
  - 'products/*/backend/**'
---

**Creating a new product? Run `hogli product:bootstrap <name>` — do not hand-roll the directory.**
The scaffold emits a product that is isolated from its first commit and passes hoglint's
Isolated level. See "New products must be isolated" in `products/README.md`.

**Otherwise, check this product's isolation status before making changes.**
Look at the product's `product.yaml`: if it sets `isolated: true`, this product claims
hoglint's Isolated level and is isolated.

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
  classes on the watched-models allowance, which `hoglint.ledger` holds as debt
  (see `products/architecture.md` § Wiring couplings).
  hoglint derives the files a change to which re-runs the full suite (`hoglint watched`);
  there is no list to edit. When `hoglint check` says the product fails the level, fix
  each reason in the code. Removing the claim needs a person.
- **Not isolated** (no `isolated: true`): hoglint still blocks new boundary findings for it,
  and its old ones are debt in `hoglint.ledger`. Prefer existing facades when they exist
  rather than importing internals.

If you need to extend what's reachable across a boundary, add a function to the relevant
facade module (or a re-export to its wiring submodule). Do not edit `hoglint.ledger` or
add an exception to `hoglint.exceptions.toml` to make a check pass: a person decides those.
Run `hoglint check` to verify the boundaries. hoglint judges tests like production code,
so a test may import any product's facade but never its internals.
