---
paths:
  - 'posthog/api/**'
  - 'products/*/backend/api/**'
  - 'products/*/backend/presentation/**'
---

Invoke the `/improving-drf-endpoints` skill before editing any viewset or serializer here.
Every viewset method must have schema annotations (`@validated_request` or `@extend_schema`).
Every serializer field must have `help_text`.
