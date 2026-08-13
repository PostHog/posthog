/** The one field this module needs off a task: which task a list row is. */
export interface ArchiveSyncTask {
  id: string;
}

/** How many tasks one pass mirrors onto the server. */
export const SERVER_ARCHIVE_SYNC_BATCH = 25;

/**
 * Which locally-archived tasks the server hasn't been told about.
 *
 * Archiving is a per-device act, so the server keeps listing sessions this
 * machine has hidden — and its count is what a space row's "view all" number
 * comes from, which is why that number can run hundreds above the list behind
 * it. Anything still in a list response that this device has archived is out of
 * sync.
 *
 * `handled` is the ids a pass has already sent (or given up on), so a failing
 * task can't be retried on every render.
 *
 * Capped, because a device with hundreds of archived sessions would otherwise
 * fire hundreds of requests at once. A synced task drops out of the next list
 * response, so the rest follow on later passes.
 */
export function pendingServerArchiveIds(
  tasks: readonly ArchiveSyncTask[],
  archivedTaskIds: ReadonlySet<string>,
  handled: ReadonlySet<string>,
  limit: number = SERVER_ARCHIVE_SYNC_BATCH,
): string[] {
  const pending: string[] = [];
  for (const task of tasks) {
    if (pending.length >= limit) break;
    if (!archivedTaskIds.has(task.id) || handled.has(task.id)) continue;
    pending.push(task.id);
  }
  return pending;
}
