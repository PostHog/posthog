/**
 * Which locally-archived tasks the server hasn't been told about.
 *
 * Archiving is a per-device act, so the server keeps listing sessions this
 * machine has hidden — and its count is what a space row's "view all" number
 * comes from, which is why that number can run hundreds above the list behind
 * it. The whole local archive is the work list: discovering the backlog
 * through a task-list page starves, because pages are capped at the newest
 * hundred rows and an archive is precisely the sessions too old to be there.
 *
 * `skip` is the ids already mirrored (durably, on this device) plus the ones
 * this run has already tried, so a task the server keeps refusing can't spin
 * the drain loop.
 */
export function pendingServerArchiveIds(
  archivedTaskIds: ReadonlySet<string>,
  skip: ReadonlySet<string>,
): string[] {
  const pending: string[] = [];
  for (const taskId of archivedTaskIds) {
    if (!skip.has(taskId)) pending.push(taskId);
  }
  return pending;
}
