import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { useService } from "@posthog/di/react";
import {
  openTab,
  primaryWindow,
  type TabIdentity,
  type TabLocation,
} from "@posthog/shared";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { useRouter } from "@tanstack/react-router";
import { useCallback } from "react";
import { pushTabHistoryEntry } from "./tabHistory";
import {
  applyLocalTransform,
  persistWrite,
  readMirror,
  reseedMirror,
} from "./tabsSync";

/** Nav state and label cache to restore alongside the href — what a reopened
 * tab carries so it comes back on the page it was on, not that route's root. */
export type OpenBrowserTabState = Partial<TabLocation & TabIdentity>;

export type OpenBrowserTab = (
  href: string,
  state?: OpenBrowserTabState,
) => void;

/** Open and focus an independent tab without waiting for host persistence. */
export function useOpenBrowserTab(): OpenBrowserTab {
  const client = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  const logger = useService<RootLogger>(ROOT_LOGGER);
  const router = useRouter();

  const openInWindow = useCallback(
    (windowId: string, href: string, state?: OpenBrowserTabState): void => {
      const tabId = crypto.randomUUID();
      const input = {
        windowId,
        tabId,
        href,
        viewState: null,
        dashboardId: null,
        taskId: null,
        channelId: null,
        channelSection: null,
        appView: null,
        ...state,
      };
      applyLocalTransform(
        (snapshot) =>
          openTab(snapshot, {
            ...input,
            makeId: () => tabId,
            now: Date.now,
          }).snapshot,
      );
      pushTabHistoryEntry(router.history, href, tabId);
      void persistWrite(() => client.openTab(input));
    },
    [client, router.history],
  );

  return useCallback(
    (href: string, state?: OpenBrowserTabState): void => {
      const window = primaryWindow(readMirror());
      if (window) {
        openInWindow(window.id, href, state);
        return;
      }

      void reseedMirror()
        .then((server) => {
          const seededWindow = primaryWindow(server ?? readMirror());
          if (seededWindow) {
            openInWindow(seededWindow.id, href, state);
            return;
          }
          logger.error("browser-tabs: open found no window after reseed");
        })
        .catch((error) => {
          logger.error("browser-tabs: open reseed failed", { error });
        });
    },
    [logger, openInWindow],
  );
}
