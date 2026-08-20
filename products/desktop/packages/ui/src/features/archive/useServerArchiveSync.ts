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
 * task leaves the next response, so each pass is handed the next batch.
 */
export function useServerArchiveSync(): void {
  const client = useOptionalAuthenticatedClient();
  const { data: tasks } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();
  const queryClient = useQueryClient();
  // Ids this session has sent or given up on. Without it a task the server
  // refuses would be retried on every render for as long as the app is open.
  const handled = useRef(new Set<string>());
  const running = useRef(false);

  useEffect(() => {
    if (!client || !tasks || running.current) return;
    const pending = pendingServerArchiveIds(
      tasks,
      archivedTaskIds,
      handled.current,
      SERVER_ARCHIVE_SYNC_BATCH,
    );
    if (pending.length === 0) return;

    running.current = true;
    void (async () => {
      let synced = 0;
      // Sequential: this is background repair of a backlog that can run to
      // hundreds, and it must not compete with the requests the user is
      // waiting on.
      for (const taskId of pending) {
        handled.current.add(taskId);
        try {
          await client.setTaskArchived(taskId, true);
          synced++;
        } catch (error) {
          log.warn(`Failed to archive task ${taskId} on the server`, error);
        }
      }
      running.current = false;
      if (synced === 0) return;
      // Refetches the list this pass just shortened, which both updates the
      // counts drawn from it and hands the next pass the next batch.
      await queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    })();
  }, [client, tasks, archivedTaskIds, queryClient]);
}
