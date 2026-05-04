---
paths:
  - 'tach.toml'
---

This file enforces Python import boundaries. Editing it carelessly breaks product isolation
and makes selective CI unreliable.

**Before adding a `depends_on` entry:** check whether the target product already has a facade
(`products/<name>/backend/facade/api.py`). If it does, adding `depends_on` bypasses isolation —
the correct fix is to add the missing method to that facade instead.
If no facade exists yet, adding `depends_on` is acceptable, but the long-term goal is always
a facade.

Run `tach check` to validate after any change here.
