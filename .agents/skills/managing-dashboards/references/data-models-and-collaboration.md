# Data models and collaboration

Read this reference when a feature adds persisted dashboard state, a model, or a relation between dashboard resources.

## Schema evolution

Define the rollout before you add the model or field.

1. Choose nullable, defaulted, or required state for existing rows.
2. Define the migration order for schema, backfill, constraint, and cleanup.
3. Add indexes for every detail, list, stream, export, or ordering query that uses the new state.
4. Keep old clients and old template payloads readable during the rollout.
5. Define rollback behavior after new rows contain the state.
6. Use `django-migrations` for model and migration changes.

## Relation lifecycle

For each new relation, define one behavior for every operation.

| Operation               | Required decision                                           |
| ----------------------- | ----------------------------------------------------------- |
| Delete parent           | Cascade, set null, soft-delete, or reject                   |
| Delete related resource | Cascade, clear relation, or reject                          |
| Restore                 | Restore the relation, leave it absent, or report a conflict |
| Duplicate               | Copy, deep-copy, or reset                                   |
| Template                | Serialize, substitute, or omit                              |
| Project transfer        | Copy, transform, or exclude                                 |
| Cross-team request      | Reject before reading the relation                          |

Do not leave orphan handling to an implicit database default. Test every selected behavior.

## Query shapes

Write the required query shape before you add a serializer field or a relation.

- Dashboard detail: select and prefetch every relation the serializer reads.
- Dashboard stream: load the same relation before the async generator starts.
- Dashboard list: avoid relation work that the list does not display.
- Export and public share: load only fields that the surface can expose.
- Reorder and mutation endpoints: lock or validate rows that must remain consistent.
- Add query-count tests when a new relation can create per-dashboard or per-tile queries.

## Concurrent editing

Choose the conflict contract for every mutation that changes multiple rows, ordering, or layout.

1. Choose last-write-wins, version check, merge, or reject-on-conflict.
2. Define the client response to a stale write.
3. Define optimistic update rollback after an API failure.
4. Keep related writes in one narrow transaction.
5. Check concurrent reorder, tile move, delete, and duplicate requests.
6. Check stale responses after dashboard, filter, variable, or placement changes.

State the chosen contract in tests. Do not rely on incidental request order.

## Accessibility and public content

For a new dashboard control or user-authored content, check both accessibility and shared output.

- Support keyboard operation for every interactive action.
- Keep focus order stable after insert, delete, collapse, expand, or reorder.
- Give controls an accessible name and state.
- Do not require drag-only interaction.
- Decide whether new user-authored text, labels, descriptions, or configuration are safe for public share, embed, and export.
- Apply the same content-safety rule to successful and error responses.

Use `writing-user-facing-copy` for new labels, help text, empty states, and errors.

## Test matrix

| Risk           | Test                                                                    |
| -------------- | ----------------------------------------------------------------------- |
| Migration      | Old row, new row, old payload, and backfill state                       |
| Relation       | Create, delete, restore, duplicate, template, and transfer              |
| Query shape    | Detail, stream, list, export, and public share query count              |
| Collaboration  | Concurrent mutation, stale write, optimistic rollback, and refresh race |
| Accessibility  | Keyboard action, focus movement, accessible name, and state             |
| Public content | Shared, embedded, export, and error payload                             |
