import type { NewTaskLinkAnalytics } from "@posthog/core/deep-links/identifiers";
import {
  NEW_TASK_LINK_RESOLVER,
  type NewTaskLinkResolver,
} from "@posthog/core/deep-links/newTaskLinkResolver";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { NewTaskLinkPayload } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useCallback, useEffect, useRef } from "react";

const log = logger.scope("new-task-deep-link");

function trackResolution(analytics: NewTaskLinkAnalytics) {
  switch (analytics.event) {
    case ANALYTICS_EVENTS.DEEP_LINK_NEW_TASK:
      return track(analytics.event, analytics.properties);
    case ANALYTICS_EVENTS.DEEP_LINK_PLAN:
      return track(analytics.event, analytics.properties);
    case ANALYTICS_EVENTS.DEEP_LINK_ISSUE:
      return track(analytics.event, analytics.properties);
    case ANALYTICS_EVENTS.DEEP_LINK_ISSUE_FAILED:
      return track(analytics.event, analytics.properties);
  }
}

export function useNewTaskDeepLink() {
  const client = useHostTRPCClient();
  const resolver = useService<NewTaskLinkResolver>(NEW_TASK_LINK_RESOLVER);
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const hasFetchedPending = useRef(false);

  const handleAction = useCallback(
    async (payload: NewTaskLinkPayload) => {
      log.info(`Handling deep link action: ${payload.action}`);
      useTaskInputPrefillStore.getState().clearReportAssociation();

      const result = await resolver.resolve(payload);
      trackResolution(result.analytics);

      if (result.kind === "navigate") {
        openTaskInput(result.navigation);
        return;
      }

      toast.error(result.title, { description: result.description });
      log.warn(result.title, result.description);
    },
    [resolver],
  );

  useEffect(() => {
    if (!isAuthenticated) {
      hasFetchedPending.current = false;
      return;
    }
    if (hasFetchedPending.current) return;

    const fetchPending = async () => {
      hasFetchedPending.current = true;
      try {
        const pending = await client.deepLink.getPendingNewTaskLink.query();
        if (pending) {
          log.info(`Found pending new task link: action=${pending.action}`);
          handleAction(pending).catch((error) => {
            log.error("Failed to handle pending new task link:", error);
          });
        }
      } catch (error) {
        hasFetchedPending.current = false;
        log.error("Failed to check for pending new task link:", error);
      }
    };

    fetchPending();
  }, [isAuthenticated, handleAction, client]);

  useEffect(() => {
    const subscription = client.deepLink.onNewTaskAction.subscribe(undefined, {
      onData: (data) => {
        log.info(`Received new task link event: action=${data.action}`);
        handleAction(data).catch((error) => {
          log.error("Failed to handle new task link action:", error);
        });
      },
    });
    return () => subscription.unsubscribe();
  }, [client, handleAction]);
}
