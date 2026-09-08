# Task comments

The desktop comments panel reads task, artifact, and canvas comments from
`/api/projects/{project_id}/comments/`. Each request supplies `scope`, `item_id`,
and `task_id`.

## Older resource comments

Older artifact and canvas comments can have no `taskId` in `item_context`.
An authorized resource query includes these comments, including rows with a null
context or a missing, null, or empty `taskId`. The API still checks task visibility
and verifies that the resource belongs to the requested task. Comments with a
stored non-empty `taskId` for another task remain excluded. Requests without an
owning task do not return task-scoped comments.

A reply keeps its root comment's target and context. If an older resource comment
has no task ID, the reply can supply one. The API checks access to that task and
resource before it saves the reply. A reply cannot replace a root's existing task
ID. No stored comment is changed during a read.
