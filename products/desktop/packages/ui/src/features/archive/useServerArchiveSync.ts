import {
  ARCHIVE_CLIENT,
  type ArchiveClient,
} from "@posthog/core/archive/identifiers";
import { pendingServerArchiveIds } from "@posthog/core/archive/serverArchiveSync";
import { useService } from "@posthog/di/react";
import { useServerArchiveSyncStore } from "@posthog/ui/features/archive/serverArchiveSyncStore";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useServerArchiveScope } from "./useServerArchiveScope";

const log = logger.scope("server-archive-sync");
const SERVER_ARCHIVE_IMPORT_LIMIT = 100;

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

/** Keep the local archive and the shared server archive aligned across devices. */
export function useServerArchiveSync(): void {
  const client = useOptionalAuthenticatedClient();
  const serverArchiveScope = useServerArchiveScope();
  const archiveClient = useService<ArchiveClient>(ARCHIVE_CLIENT);
  const archivedTaskIds = useArchivedTaskIds();
  const queryClient = useQueryClient();
  // Queued restores re-fire the effect. Mirrored-id progress deliberately
  // doesn't: this hook lives at the root, and subscribing to a record that
  // grows once per PATCH would re-render the tree hundreds of times per drain.
  const pendingUnarchive = useServerArchiveSyncStore(
    (s) => s.pendingUnarchiveTaskIds,
  );
  const [drainGeneration, setDrainGeneration] = useState(0);
  const running = useRef(false);
  const rerunRequested = useRef(false);
  const archivedRef = useRef(archivedTaskIds);
  const clientRef = useRef(client);
  const archiveClientRef = useRef(archiveClient);
  const importedScopes = useRef(new Set<string>());

  // The drain loop re-reads these between passes. If a trigger lands too late
  // for the running drain to see it, rerunRequested starts another pass.
  useEffect(() => {
    archivedRef.current = archivedTaskIds;
    clientRef.current = client;
    archiveClientRef.current = archiveClient;
  });

  useEffect(() => {
    if (!client) return;
    if (running.current) {
      rerunRequested.current = true;
      return;
    }
    const mirrored = new Set(
      useServerArchiveSyncStore.getState().syncedTaskIds,
    );

    running.current = true;
    void (async () => {
      // Ids this run has already tried and the server refused — retried on the
      // next launch or trigger, but not by the very next pass of this loop.
      const attempted = new Set<string>();
      let serverChanges = 0;
      let imported = 0;
      log.info("Synchronizing archive state", {
        archivedLocally: archivedTaskIds.size,
        alreadyMirrored: mirrored.size,
        drainGeneration,
        pendingUnarchive: pendingUnarchive.length,
      });
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
            serverChanges++;
          } catch (error) {
            attempted.add(taskId);
            log.warn(`Failed to unarchive task ${taskId} on the server`, error);
          }
        }
        for (const taskId of archive) {
          try {
            await api.setTaskArchived(taskId, true);
            store.markSynced(taskId);
            serverChanges++;
          } catch (error) {
            attempted.add(taskId);
            log.warn(`Failed to archive task ${taskId} on the server`, error);
          }
        }
      }
      try {
        const api = clientRef.current;
        if (
          api &&
          serverArchiveScope !== null &&
          !importedScopes.current.has(serverArchiveScope)
        ) {
          importedScopes.current.add(serverArchiveScope);
          const store = useServerArchiveSyncStore.getState();
          const offset = store.archiveImportOffsets[serverArchiveScope] ?? 0;
          const serverArchive = await api.getTasksPage({
            archived: true,
            limit: SERVER_ARCHIVE_IMPORT_LIMIT,
            offset,
          });
          const pendingUnarchiveIds = new Set(store.pendingUnarchiveTaskIds);
          let importFailed = false;
          for (const task of serverArchive.tasks) {
            if (pendingUnarchiveIds.has(task.id)) {
              continue;
            }
            if (archivedRef.current.has(task.id)) {
              useServerArchiveSyncStore.getState().markSynced(task.id);
              continue;
            }
            try {
              await archiveClientRef.current.archive({
                taskId: task.id,
                title: task.title,
                taskCreatedAt: task.created_at,
                repository: task.repository,
                serverArchiveScope,
              });
              useServerArchiveSyncStore.getState().markSynced(task.id);
              imported++;
            } catch (error) {
              importFailed = true;
              log.warn(
                `Failed to import archived task ${task.id} from the server`,
                error,
              );
            }
          }
          if (!importFailed) {
            const reachedEnd =
              serverArchive.tasks.length === 0 ||
              offset + serverArchive.tasks.length >= serverArchive.count;
            store.setArchiveImportOffset(
              serverArchiveScope,
              reachedEnd ? 0 : offset + serverArchive.tasks.length,
            );
          }
        }
      } catch (error) {
        log.warn("Failed to read archived tasks from the server", error);
      }
      log.info("Archive drain finished", {
        synced: serverChanges,
        imported,
        refused: attempted.size,
      });
      if (serverChanges > 0 || imported > 0) {
        await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      }
      if (imported > 0) {
        await archiveClientRef.current.refreshArchiveState();
      }
    })().finally(() => {
      running.current = false;
      if (rerunRequested.current) {
        rerunRequested.current = false;
        setDrainGeneration((value) => value + 1);
      }
    });
  }, [
    archivedTaskIds,
    client,
    pendingUnarchive,
    queryClient,
    drainGeneration,
    serverArchiveScope,
  ]);
}
