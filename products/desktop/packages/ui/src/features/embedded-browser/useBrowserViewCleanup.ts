import type { PanelNode } from "@posthog/core/panels/panelTypes";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useEffect } from "react";
import { useHostCapabilities } from "../../shell/useHostCapabilities";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { browserViewId } from "./browserViewId";

function collectBrowserTabIds(node: PanelNode | undefined): Set<string> {
  const ids = new Set<string>();
  const walk = (current: PanelNode) => {
    if (current.type === "leaf") {
      for (const tab of current.content.tabs) {
        if (tab.data.type === "browser") ids.add(tab.id);
      }
      return;
    }
    for (const child of current.children) walk(child);
  };
  if (node) walk(node);
  return ids;
}

function destroyViews(
  client: Pick<HostTrpcClient, "embeddedBrowser">,
  taskId: string,
  tabIds: Iterable<string>,
): void {
  for (const tabId of tabIds) {
    // Destroying a view that was never created is a no-op host-side; a
    // failure only means the view is already gone.
    void client.embeddedBrowser.destroy
      .mutate({ viewId: browserViewId(taskId, tabId) })
      .catch(() => {});
  }
}

/**
 * Native views outlive their tabs unless someone reconciles: a browser tab
 * can leave the layout through paths that never tell its panel component it
 * was closed rather than switched away from (close-others, close-to-right,
 * closing a whole panel). Watching the layout and destroying views whose
 * tabs disappeared covers every close path with one rule.
 */
export function useBrowserViewCleanup(taskId: string): void {
  const client = useHostTRPCClient();
  const { embeddedBrowser } = useHostCapabilities();

  useEffect(() => {
    if (!embeddedBrowser) return;
    let prev = collectBrowserTabIds(
      usePanelLayoutStore.getState().taskLayouts[taskId]?.panelTree,
    );
    return usePanelLayoutStore.subscribe((state) => {
      const next = collectBrowserTabIds(state.taskLayouts[taskId]?.panelTree);
      const removed = [...prev].filter((id) => !next.has(id));
      if (removed.length > 0) destroyViews(client, taskId, removed);
      prev = next;
    });
  }, [taskId, client, embeddedBrowser]);
}

/**
 * Destroy every browser view belonging to a task. Mirrors
 * `destroyTaskTerminals`: called from task lifecycle (delete), not from tab
 * close — the reconciler above owns that. Resolves the host client the same
 * way `openExternalUrl` does so lifecycle code can call it as a plain
 * function.
 */
export function destroyTaskBrowserViews(taskId: string): void {
  const layout = usePanelLayoutStore.getState().taskLayouts[taskId];
  const tabIds = collectBrowserTabIds(layout?.panelTree);
  if (tabIds.size === 0) return;
  const client = resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
  destroyViews(client, taskId, tabIds);
}
