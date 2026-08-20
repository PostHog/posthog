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
  const archivedRef = useRef(archivedTaskIds);
  const clientRef = useRef(client);

  // The drain loop re-reads these between passes, so a session archived while
  // it runs is picked up by the loop that's already going, and the effect that
  // fires for it lands on the `running` guard and is skipped. Written after the
  // render rather than during it, and before the drain effect below, which runs
  // later in the same commit — so the drain never reads a ref left behind by a
  // render React went on to discard.
  useEffect(() => {
    archivedRef.current = archivedTaskIds;
    clientRef.current = client;
  });

  useEffect(() => {
    if (!client || running.current) return;
    // The triggers, checked directly: don't start a drain that would find
    // nothing. The loop below re-reads both sources fresh each pass.
    const mirrored = new Set(
      useServerArchiveSyncStore.getState().syncedTaskIds,
    );
    if (
      pendingUnarchive.length === 0 &&
      pendingServerArchiveIds(archivedTaskIds, mirrored).length === 0
    ) {
      // Distinguishes "nothing to mirror" from "never ran" — the two are
      // otherwise identical in the console, and each app instance has its own
      // archive DB (dev vs packaged), so an unexpectedly small count here is
      // the tell that you're looking at the other instance's backlog.
      log.debug("Archive sync idle", {
        archivedLocally: archivedTaskIds.size,
        alreadyMirrored: mirrored.size,
      });
      return;
    }

    running.current = true;
    void (async () => {
      // Ids this run has already tried and the server refused — retried on the
      // next launch or trigger, but not by the very next pass of this loop.
      const attempted = new Set<string>();
      let changed = 0;
      // The drain's outcome IS the diagnosis when a count reads wrong, and a
      // run that finds work is rare (once per backlog) — so say what was found
      // and what happened to it, not just the failures.
      log.info("Draining archive state to the server", {
        archivedLocally: archivedTaskIds.size,
        alreadyMirrored: mirrored.size,
        pendingUnarchive: pendingUnarchive.length,
      });
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
          // No await stands between this read and the guard release below, so
          // a trigger either lands early enough for the next pass to see it or
          // late enough to start its own drain. There is no gap to lose one in.
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
      log.info("Archive drain finished", {
        synced: changed,
        refused: attempted.size,
      });
      if (changed === 0) return;
      // Refetches the lists the drain just shortened, which is what moves the
      // space counts drawn from them.
      await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    })();
  }, [client, archivedTaskIds, pendingUnarchive, queryClient]);
}
