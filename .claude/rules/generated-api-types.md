---
paths:
  - 'frontend/src/**'
  - 'products/*/frontend/**'
---

If this file calls `api.get<`, `api.create<`, `new ApiRequest()`, or uses handwritten API types, read
["Rule 3 — Don't handwrite API types"](../../frontend/src/AGENTS.md#rule-3--dont-handwrite-api-types-use-the-generated-ones)
and invoke the `/adopting-generated-api-types` skill before making changes.
