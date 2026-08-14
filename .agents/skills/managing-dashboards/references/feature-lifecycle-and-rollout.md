# Feature lifecycle and rollout

## Choose the feature contract first

For a new dashboard feature, record these decisions before you select implementation files.

| Decision      | Required answer                                               |
| ------------- | ------------------------------------------------------------- |
| Actor         | Who uses the feature?                                         |
| State owner   | Dashboard, tile, request, user, or URL?                       |
| Default       | What do existing and new dashboards do?                       |
| Availability  | Available to every project, feature-gated, or product-gated?  |
| Authorization | Who can view and change the feature?                          |
| Failure       | What does the user see when data, access, or execution fails? |
| Non-goal      | Which related behavior must not change?                       |

Do not use a feature flag as a substitute for a permission check.

## Lifecycle matrix

For persisted feature state, mark each operation as `preserve`, `copy`, `reset`, `omit`, or `not applicable`.

| Operation                 | Decision                            |
| ------------------------- | ----------------------------------- |
| Create dashboard          | Default state                       |
| Update dashboard          | Validation and authorization        |
| Duplicate dashboard       | Copy or reset state                 |
| Create from template      | Copy, substitute, or omit state     |
| Save as template          | Include or omit state               |
| Move or copy tile         | Preserve, copy, or reset state      |
| Public share and embed    | Render, hide, or use a safe default |
| Export                    | Render, omit, or use a safe default |
| Product-created dashboard | Stable creation and default state   |
| Resource transfer         | Copy, transform, or exclude state   |
| Soft delete and restore   | Preserve or reset state             |

If the feature adds a relation, read [data models and collaboration](data-models-and-collaboration.md#relation-lifecycle).

## Availability and rollout

If the feature needs a gate, define:

1. The gate name and evaluation actor.
2. The default when the gate is off.
3. The data written while the gate is off.
4. The rollback behavior after data exists.
5. The gate-removal condition and owner.

Check both the backend and frontend gate. The backend must reject a mutation that the frontend hides.

## Acceptance criteria and test layers

Write acceptance criteria before you write tests.

| Acceptance criterion                       | Preferred test layer               |
| ------------------------------------------ | ---------------------------------- |
| Validation, tenant boundary, or permission | Backend unit or API test           |
| Persisted request and response contract    | API test plus generated-type check |
| Client state, preview, or request shape    | Frontend logic test                |
| Placement-specific visibility or action    | Component test                     |
| Critical user journey across layers        | Playwright test                    |

At minimum, state an acceptance criterion for each affected case:

- Allowed actor
- Denied actor
- New dashboard
- Existing dashboard
- Shared, embedded, or export surface
- Invalid, absent, or old state
- Query, cache, or network failure
- Concurrent edit or stale client state, when the feature mutates persisted state

## Operational contract

Before rollout, state:

- Expected request-count change
- Expected cache behavior
- Expected database-read and database-write change
- Adoption signal
- Error or latency signal
- Alert requirement, if the feature adds a material operational risk

Use existing endpoint monitoring when it covers the path. Add new metrics only when they answer a new operational question.

## Documentation

If the feature changes a user-visible setting, API, shared behavior, or documented workflow, update the matching documentation in the same change.

Use `writing-user-facing-copy` for new UI text. Keep rollout notes outside code comments.
