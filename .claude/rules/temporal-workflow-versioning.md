---
paths:
  - 'posthog/temporal/**'
  - 'products/*/backend/temporal/**'
---

Editing a `@workflow.defn` body breaks in-flight executions. Read
[Version a workflow before you edit its body](../../posthog/temporal/README.md#version-a-workflow-before-you-edit-its-body)
before adding, removing, or reordering `execute_activity` calls, child-workflow starts, or timers.
