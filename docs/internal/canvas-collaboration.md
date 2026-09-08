# Canvas collaboration

## Access

Signed-in project members can edit canvases in public spaces. A task-bound sandbox
with an authenticated user has the same content access. It must use its bound task ID.
Personal-space canvases remain private to their owner. Team boundaries do not change.

Members can publish source, edit files, rebuild the current version, stage drafts,
promote drafts, and revert versions. They can also edit canvas context and record
their own generation task. Only the canvas creator can rename, move, pin, describe,
or delete the canvas. The publish and edit endpoints reject a non-creator's `name`
field with HTTP 403, without saving source or changing the current version.

## Publishing and recovery

Agent runs publish by default. Ask for a draft or a review step to keep a change
off the live canvas. A publish creates a source version and queues its build.
The live artifact changes only after a successful build. A failed build leaves
the last successful artifact available.

Use `expected_current_version_id` when publishing. A stale version returns HTTP 409.
Read the current source, apply the change again, and retry against that version.
Use version history to inspect earlier source and revert an unwanted change.
Version history shows the publisher and links to the publishing task without
assuming that the task belongs to the canvas's current space.

## Agent sessions

The canvas panel shows the active run's chat. After the run finishes, edit mode
shows a new composer. View mode shows an empty chat state. Comments remain attached
to the earlier task. Each new edit starts a new task and session.

## Release checks

The desktop changes use existing endpoints and version fields. They can ship before
or after the backend changes. The backend still controls write access. An older
backend continues to reject shared edits until the new permissions reach it.

Check shared edits with both a signed-in member and a task-bound sandbox. Confirm
that name changes fail for non-creators, personal-space access stays private, and
stale publishes return HTTP 409. Confirm that a finished run returns to the composer
and that a version's task link does not use the canvas's space ID.

Use the existing `canvas published` events and canvas build results to check publish
activity and failures after release. No new analytics events are required.
