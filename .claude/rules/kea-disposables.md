---
paths:
  - 'frontend/src/**/*Logic.ts'
  - 'frontend/src/**/*Logic.tsx'
  - 'products/*/frontend/**/*Logic.ts'
  - 'products/*/frontend/**/*Logic.tsx'
---

If this kea logic adds a resource that needs cleanup, read
["Cleanup in a logic goes through disposables"](../../frontend/src/AGENTS.md#rule-4--business-logic-in-kea-not-react-hooks)
and invoke the `/using-kea-disposables` skill before making changes.
