---
paths:
  - 'products/*/backend/**'
---

**Check this product's isolation status before making changes.**
Look at the product's `package.json`: if `backend:contract-check` is listed under `scripts`,
this product is isolated.

- **Isolated:** external code (core, other products) may only import from
  `backend/facade/api.py`. Do not expose internal modules directly, and do not add
  raw cross-product imports — go through the target product's facade instead.
- **Not isolated:** boundaries are not yet enforced by CI, but prefer using existing
  facades when they exist rather than importing internals.

If you need to extend what's reachable across a boundary, add a method to the relevant
`backend/facade/api.py` — not a `depends_on` entry in `tach.toml`.
Run `tach check --dependencies --interfaces` to verify import boundaries are clean.
