import { pendingServerArchiveIds } from "@posthog/core/archive/serverArchiveSync";
import { useServerArchiveSyncStore } from "@posthog/ui/features/archive/serverArchiveSyncStore";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

const log = logger.scope("server-archive-sync");

/**
 * A restore that couldn't reach the server. Until the clear lands the session
 * is archived server-side, which hides it from every list — including this
 * device's, where it was just restored — so the queue is durable and the sync
 * pass keeps trying.
 */
export function retryServerUnarchive(taskId: string): void {
  const store = useServerArchiveSyncStore.getState();
  store.forgetSynced(taskId);
  store.queueUnarchive(taskId);
}

/** A restored task, which may well be archived again before long. */
export function forgetServerArchive(taskId: string): void {
  useServerArchiveSyncStore.getState().forgetSynced(taskId);
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
 * The work list is the local archive itself, diffed against a durable record of
 * what this device has already mirrored — not a task-list page. Pages are
 * capped at the newest hundred rows, and an archive is precisely the sessions
 * too old to be there: discovery through a page synced whatever happened to be
 * recent and then starved. The drain runs once per backlog ever (the record
 * survives relaunch), sequentially, so it never competes with requests the
 * user is waiting on.
 */
export function useServerArchiveSync(): void {
  const client = useOptionalAuthenticatedClient();
  const archivedTaskIds = useArchivedTaskIds();
  const queryClient = useQueryClient();
  // Queued restores re-fire the effect. Mirrored-id progress deliberately
  // doesn't: this hook lives at the root, and subscribing to a record that
  // grows once per PATCH would re-render the tree hundreds of times per drain.
  const pendingUnarchive = useServerArchiveSyncStore(
    (s) => s.pendingUnarchiveTaskIds,
  );
  const running = useRef(false);
  // The drain loop re-reads these between passes, so sessions archived while
  // it runs are picked up by the loop that's already going — the effect that
  // fires for them lands on the `running` guard and is skipped.
  const archivedRef = useRef(archivedTaskIds);
  archivedRef.current = archivedTaskIds;
  const clientRef = useRef(client);
  clientRef.current = client;

  useEffect(() => {
    if (!client || running.current) return;

    running.current = true;
    void (async () => {
      // Ids this run has already tried and the server refused — retried on the
      // next launch or trigger, but not by the very next pass of this loop.
      const attempted = new Set<string>();
      let changed = 0;
      try {
        for (;;) {
          const api = clientRef.current;
          if (!api) break;
          const store = useServerArchiveSyncStore.getState();
          const unarchive = store.pendingUnarchiveTaskIds.filter(
            (id) => !attempted.has(id),
          );
          const archive = pendingServerArchiveIds(
            archivedRef.current,
            new Set([...store.syncedTaskIds, ...attempted]),
          );
          if (unarchive.length === 0 && archive.length === 0) break;

          // Restores lead: a session the server still has archived is
          // invisible everywhere, which is worse than a count that reads high.
          for (const taskId of unarchive) {
            try {
              await api.setTaskArchived(taskId, false);
              store.clearUnarchive(taskId);
              store.forgetSynced(taskId);
              changed++;
            } catch (error) {
              attempted.add(taskId);
              log.warn(
                `Failed to unarchive task ${taskId} on the server`,
                error,
              );
            }
          }
          for (const taskId of archive) {
            try {
              await api.setTaskArchived(taskId, true);
              store.markSynced(taskId);
              changed++;
            } catch (error) {
              attempted.add(taskId);
              log.warn(`Failed to archive task ${taskId} on the server`, error);
            }
          }
        }
      } finally {
        running.current = false;
      }
      if (changed === 0) return;
      // Refetches the lists the drain just shortened, which is what moves the
      // space counts drawn from them.
      await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    })();
  }, [client, archivedTaskIds, pendingUnarchive, queryClient]);
}
