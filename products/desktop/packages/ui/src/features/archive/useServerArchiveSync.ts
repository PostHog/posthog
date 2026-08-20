import {
  pendingServerArchiveIds,
  SERVER_ARCHIVE_SYNC_BATCH,
} from "@posthog/core/archive/serverArchiveSync";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

const log = logger.scope("server-archive-sync");

/**
 * Ids already mirrored onto the server, and restores whose clear didn't land.
 *
 * Module state rather than refs on the hook: the hook mounts once, and the
 * restore path has to reach both sets — a restored task has to be forgotten
 * (archiving it again later in the session would otherwise be skipped as
 * already sent), and a failed clear has to leave something behind to retry.
 */
const syncedTaskIds = new Set<string>();
const pendingUnarchiveIds = new Set<string>();

/**
 * A restore that couldn't reach the server. Until the clear lands the session
 * is archived server-side, which hides it from every list — including this
 * device's, where it was just restored — so the next pass tries again.
 */
export function retryServerUnarchive(taskId: string): void {
  syncedTaskIds.delete(taskId);
  pendingUnarchiveIds.add(taskId);
}

/** A restored task, which may well be archived again before the app closes. */
export function forgetServerArchive(taskId: string): void {
  syncedTaskIds.delete(taskId);
}

/**
 * Tell the server about the sessions this device has archived.
 *
 * Archiving has always been local, so the server kept listing sessions the app
 * hides. Its count is what a space row's "view all" number is drawn from, which
 * left that number reading hundreds above the list it leads to. Marking the
 * task archived server-side drops it from the same list every count comes from,
 * and carries the archive to the user's other devices.
 *
 * A reconciler rather than a call in the archive path: it fixes archives made
 * before this shipped, and one made while offline, without any of them needing
 * a queue to sit in. It rides the task poll the app already runs — a synced
 * task leaves the next response, so each pass is handed the next batch, and a
 * failed one is simply picked up again on the pass after.
 */
export function useServerArchiveSync(): void {
  const client = useOptionalAuthenticatedClient();
  const { data: tasks } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();
  const queryClient = useQueryClient();
  const running = useRef(false);

  useEffect(() => {
    if (!client || !tasks || running.current) return;
    const unarchive = [...pendingUnarchiveIds];
    const archive = pendingServerArchiveIds(
      tasks,
      archivedTaskIds,
      syncedTaskIds,
      SERVER_ARCHIVE_SYNC_BATCH,
    );
    if (unarchive.length === 0 && archive.length === 0) return;

    running.current = true;
    void (async () => {
      let changed = 0;
      // Restores lead: a session the server still has archived is invisible
      // everywhere, which is worse than a count that reads high.
      for (const taskId of unarchive) {
        try {
          await client.setTaskArchived(taskId, false);
          pendingUnarchiveIds.delete(taskId);
          changed++;
        } catch (error) {
          log.warn(`Failed to unarchive task ${taskId} on the server`, error);
        }
      }
      // Sequential: this is background repair of a backlog that can run to
      // hundreds, and it must not compete with the requests the user is
      // waiting on. Only what landed is remembered, so anything the server
      // refused this pass is tried again on the next poll.
      for (const taskId of archive) {
        try {
          await client.setTaskArchived(taskId, true);
          syncedTaskIds.add(taskId);
          changed++;
        } catch (error) {
          log.warn(`Failed to archive task ${taskId} on the server`, error);
        }
      }
      running.current = false;
      if (changed === 0) return;
      // Refetches the list this pass just shortened, which both updates the
      // counts drawn from it and hands the next pass the next batch.
      await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    })();
  }, [client, tasks, archivedTaskIds, queryClient]);
}
