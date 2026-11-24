---
paths:
  - 'products/*/backend/**'
---

**Creating a new product? Run `hogli product:bootstrap <name>` — do not hand-roll the directory.**
The scaffold emits a product that is isolated from its first commit and passes hoglint's
Isolated level. See "New products must be isolated" in `products/README.md`.

**Otherwise, check this product's isolation status before making changes.**
Look at the product's `turbo.json`: if it narrows the `backend:contract-check` inputs,
this product claims hoglint's Isolated level and is isolated.

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
  classes on the watched-models allowance, whose hand-outs `hoglint.ledger` holds as
  debt (see `products/architecture.md` § Wiring couplings).
  When `hoglint check` names a file that the `backend:contract-check` inputs do not watch,
  add the file to the inputs. Dropping the narrowing needs a person.
- **Not isolated** (no narrowed inputs): hoglint still blocks new boundary findings for it,
  and its old ones are debt in `hoglint.ledger`. Prefer existing facades when they exist
  rather than importing internals.

An import past another product's facade (`public-surface`), a disallowed use of its model
(`model-crossings`) and an `apps.get_model` reference to it (`get-model`) only report: CI
lists them for that product's team and the ledger keeps no line for them. Every other rule
blocks.

If you need to extend what's reachable across a boundary, add a function to the relevant
facade module (or a re-export to its wiring submodule). Do not edit `hoglint.ledger` or
add an exception to `hoglint.exceptions.toml` to make a check pass: a person decides those.
Run `hoglint check` to verify the boundaries. hoglint judges tests like production code,
so a test may import any product's facade but should not import its internals.
