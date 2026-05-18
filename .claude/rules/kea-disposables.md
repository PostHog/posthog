---
paths:
  - 'frontend/src/**/*Logic.ts'
  - 'frontend/src/**/*Logic.tsx'
  - 'products/*/frontend/**/*Logic.ts'
  - 'products/*/frontend/**/*Logic.tsx'
---

If this kea logic adds `setInterval`, `setTimeout`, `addEventListener`, or any other
resource that needs cleanup, invoke the `/using-kea-disposables` skill before making
changes. Prefer `cache.disposables.add(() => ..., 'key')` over `cache.foo = setInterval(...)`
plus `beforeUnmount` cleanup — the plugin handles teardown and auto-pauses on hidden tabs.
