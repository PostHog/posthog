---
paths:
  - 'posthog/admin/**'
  - 'products/*/backend/admin.py'
---

Per-product admin is the default.
New admin classes for product models belong in `products/<name>/backend/admin.py`, not in `posthog/admin/admins/`.

Moving an existing entry out of the central registry, or adding a new product admin, is covered by the `/move-admins-to-product` skill — read it before editing here.

Push back on PRs that introduce a new admin class under `posthog/admin/admins/` for a model that lives in `products/`.
The exceptions are core posthog admins (Organization, Team, User, Dashboard, …) which legitimately stay central.
