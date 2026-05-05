---
paths:
  - 'frontend/src/**'
  - 'products/*/frontend/**'
---

If this file calls `api.get<`, `api.create<`, `new ApiRequest()`, or uses handwritten API types,
invoke the `/adopting-generated-api-types` skill before making changes.
Files under `frontend/src/generated/core/` and `products/*/frontend/generated/` are auto-generated —
never edit them manually; change the serializer and run `hogli build:openapi`.
