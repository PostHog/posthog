# Working in `products/`

Read the linked docs before changing code in a product.

- [Products README](./README.md) — folder structure, backend and frontend conventions, adding a product, separate product databases, team scoping.
- [Modular architecture and isolated testing](./architecture.md) — contracts, facades, business logic, presentation layer, isolation rules, wiring couplings.

## Creating a new product

**Run `hogli product:bootstrap <name>` — do not hand-roll the directory.**
The scaffold emits a product that is isolated from its first commit; see
["New products must be isolated"](./README.md#new-products-must-be-isolated).

## Check this product's isolation status before changing it

Look at the product's `package.json`: if `backend:contract-check` is listed under `scripts`,
this product is isolated.

**Isolated:** external code (core, other products) may only import from the
`backend/facade/` package — `api.py` for data capabilities, and capability submodules
(`queries.py`, `tasks.py`, `temporal.py`, …) for wiring that core registers or
dispatches on. Do not expose internal modules directly, and do not add raw
cross-product imports — go through the target product's facade instead.
What wiring submodules may re-export, where data and error types belong, and the frozen
`MODEL_CROSSINGS` model allowance:
[architecture.md § Wiring couplings](./architecture.md#wiring-couplings).

**Not isolated** (the product is listed in `products/isolation_baseline.txt`): boundaries
are not enforced by CI for it yet, but prefer using existing facades when they exist rather
than importing internals.
A product that is neither isolated nor on that list is a new product that skipped the
scaffold — see above.

## Extending what crosses a boundary

Add a function to the relevant facade module (or a re-export to its wiring submodule) — **not** a
`depends_on` entry in `tach.toml`, which enforces the import boundaries and, edited carelessly,
breaks isolation and selective CI. If the target product has no facade yet
(`products/<name>/backend/facade/api.py`), invoke the `/isolating-product-facade-contracts`
skill to create one.

Run `hogli lint:tach` to verify import boundaries are clean. It runs the two tach passes CI runs:
dependencies without test code, interfaces with it, so a test may import any product's public
surface without a `depends_on` entry but never its internals.
