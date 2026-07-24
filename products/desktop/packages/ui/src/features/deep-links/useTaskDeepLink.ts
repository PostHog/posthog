import { useHostTRPCClient } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { useEffect, useRef } from "react";

const log = logger.scope("task-deep-link");

/**
 * Subscribes to open-existing-task deep link events (the `posthog://task/...`
 * URL scheme) and opens the task. The open logic is shared with the generic
 * notification-target consumer via {@link useHandleOpenTask}.
 */
export function useTaskDeepLink() {
  const client = useHostTRPCClient();
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const hasFetchedPending = useRef(false);
  const handleOpenTask = useHandleOpenTask();

  // Check for pending deep link on mount (for cold start via deep link)
  useEffect(() => {
    if (!isAuthenticated || hasFetchedPending.current) return;

    const fetchPending = async () => {
      hasFetchedPending.current = true;
      try {
        const pending = await client.deepLink.getPendingDeepLink.query();
        if (pending) {
          log.info(
            `Found pending deep link: taskId=${pending.taskId}, taskRunId=${pending.taskRunId ?? "none"}`,
          );
          handleOpenTask(pending.taskId, pending.taskRunId);
        }
      } catch (error) {
        log.error("Failed to check for pending deep link:", error);
      }
    };

    fetchPending();
  }, [isAuthenticated, handleOpenTask, client]);

  // Subscribe to deep link events (for warm start via deep link)
  useEffect(() => {
    const subscription = client.deepLink.onOpenTask.subscribe(undefined, {
      onData: (data) => {
        log.info(
          `Received deep link event: taskId=${data.taskId}, taskRunId=${data.taskRunId ?? "none"}`,
        );
        if (!data?.taskId) return;
        handleOpenTask(data.taskId, data.taskRunId);
      },
    });
    return () => subscription.unsubscribe();
  }, [client, handleOpenTask]);
}
