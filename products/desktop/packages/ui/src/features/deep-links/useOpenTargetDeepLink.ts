import { useHostTRPCClient } from "@posthog/host-router/react";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { focusExistingTab } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import {
  readMirror,
  reseedMirror,
} from "@posthog/ui/features/browser-tabs/tabsSync";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import {
  navigateToChannelDashboard,
  setOpenTargetHandler,
} from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useCallback, useEffect } from "react";

const log = logger.scope("open-target-deep-link");

/** The href a target opens at, or null when the kind has no mapping. */
function openTargetHref(target: NotificationTarget): string | null {
  switch (target.kind) {
    case "task":
      return `/tasks/${target.taskId}`;
    case "canvas":
      return `/spaces/${target.channelId}/dashboards/${target.dashboardId}`;
  }
}

/**
 * Consumes generic "open this target" intents emitted when a native
 * notification is clicked (any tier, any producer) and navigates by target
 * kind. Sibling of {@link useTaskDeepLink}, which handles the task URL scheme.
 */
export function useOpenTargetDeepLink() {
  const client = useHostTRPCClient();
  const handleOpenTask = useHandleOpenTask();

  const handleTarget = useCallback(
    (target: NotificationTarget) => {
      log.info("Opening notification target", { kind: target.kind });
      switch (target.kind) {
        case "task":
          handleOpenTask(target.taskId, target.taskRunId);
          break;
        case "canvas":
          navigateToChannelDashboard(target.channelId, target.dashboardId);
          break;
      }
    },
    [handleOpenTask],
  );

  // A tab that already shows the target wins over opening a duplicate: the
  // intent becomes a tab switch, and only an unmatched target opens anew. The
  // mirror can still be unseeded right after a cold start (the click launched
  // the app), so an unmatched first look re-checks after the boot fetch.
  const handleTargetWithTabs = useCallback(
    (target: NotificationTarget) => {
      const href = openTargetHref(target);
      if (href && focusExistingTab({ href })) return;
      if (!href || readMirror().windows.length > 0) {
        handleTarget(target);
        return;
      }
      void reseedMirror().then((server) => {
        if (server && focusExistingTab({ href })) return;
        handleTarget(target);
      });
    },
    [handleTarget],
  );

  // Expose the same channel-aware routing to imperative, non-React callers (the
  // in-app notification toast's action), so a toast click and a native click
  // open a target identically.
  useEffect(() => {
    setOpenTargetHandler(handleTargetWithTabs);
    return () => setOpenTargetHandler(null);
  }, [handleTargetWithTabs]);

  useEffect(() => {
    let cancelled = false;

    // Warm path: receive clicks while the app is running.
    const subscription = client.deepLink.onOpenTarget.subscribe(undefined, {
      onData: (target) => {
        if (target && !cancelled) handleTargetWithTabs(target);
      },
    });

    // Drain anything queued while no listener was live — a cold start (app
    // launched by the click) OR a click that lands in the gap after mount /
    // an HMR or socket reconnect, before the subscription's listener registers.
    // `getPendingOpenTarget` consumes (clears) it, so repeated drains are safe.
    void client.deepLink.getPendingOpenTarget
      .query()
      .then((pending) => {
        if (pending && !cancelled) handleTargetWithTabs(pending);
      })
      .catch((error) =>
        log.error("Failed to drain pending open-target", error),
      );

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, [client, handleTargetWithTabs]);
}
