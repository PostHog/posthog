# Working in `products/`

Pointers, not content. Read the linked docs before changing code in a product.

- [Products README](./README.md) — folder structure, backend and frontend conventions, adding a product, separate product databases, team scoping.
- [Modular architecture and isolated testing](./architecture.md) — contracts, facades, business logic, presentation layer, isolation rules, wiring couplings.

## Creating a new product

**Run `hogli product:bootstrap <name>` — do not hand-roll the directory.**
The scaffold emits a product that is isolated from its first commit, and `product:lint --all`
fails on a new product that is not. See ["New products must be isolated"](./README.md#new-products-must-be-isolated).

## Check this product's isolation status before changing it

Look at the product's `package.json`: if `backend:contract-check` is listed under `scripts`,
this product is isolated.

**Isolated:** external code (core, other products) may only import from the
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
(see [architecture.md § Wiring couplings](./architecture.md#wiring-couplings)).

**Not isolated** (the product is listed in `products/isolation_baseline.txt`): boundaries
are not enforced by CI for it yet, but prefer using existing facades when they exist rather
than importing internals.
A product that is neither isolated nor on that list is a new product that skipped the
scaffold — see above.

## Extending what crosses a boundary

Add a function to the relevant facade module (or a re-export to its wiring submodule) — **not** a
`depends_on` entry in `tach.toml`.

`tach.toml` enforces Python import boundaries. Editing it carelessly breaks product isolation and
makes selective CI unreliable. Before adding a `depends_on` entry, check whether the target product
already has a facade (`products/<name>/backend/facade/api.py`). If it does, adding `depends_on`
bypasses isolation; add the missing method to that facade instead. If no facade exists yet, invoke
the `/isolating-product-facade-contracts` skill to create one rather than adding a raw `depends_on`.

Run `tach check --dependencies --interfaces` to verify import boundaries are clean.
