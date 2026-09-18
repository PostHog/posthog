import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { useService } from "@posthog/di/react";
import { primaryWindow, setTabOrder } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { isTileDropData } from "@posthog/ui/features/tab-tiling/TileDropZones";
import { isTileTabDragData } from "@posthog/ui/features/tab-tiling/tileDrag";
import { useTileLayoutStore } from "@posthog/ui/features/tab-tiling/tileLayoutStore";
import {
  groupForTab,
  type TileEdge,
  tabIdsIn,
} from "@posthog/ui/features/tab-tiling/tileTree";
import { track } from "@posthog/ui/shell/analytics";
import { type ReactNode, useRef } from "react";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "./browserTabsClient";
import { reorderWithinGroup, storedOrderIds } from "./displayOrder";
import { usePinnedTabsStore } from "./pinnedTabsStore";
import { isStripDropData } from "./stripDrop";
import { exceedsDetachDistance } from "./tabDetach";
import { useTabReorderStore } from "./tabReorderStore";
import { applyLocalTransform, persistWrite, readMirror } from "./tabsSync";
import { useGoToTab } from "./useGoToTab";

function sameOrder(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

function resetDragState(): void {
  const store = useTabReorderStore.getState();
  store.setPreviewOrder(null);
  store.setDraggingTabId(null);
  store.setDragSource(null);
  store.setDetached(false);
}

function tileBeside(tabId: string, targetTabId: string, edge: TileEdge): void {
  useTileLayoutStore.getState().tileTab(tabId, targetTabId, edge);
  const group = groupForTab(useTileLayoutStore.getState().groups, targetTabId);
  track(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
    edge,
    tile_count: group ? tabIdsIn(group.root).length : 0,
  });
}

/**
 * DnD scope for browser-tab strip drags, mounted around the channels chrome.
 * Handlers ignore any drag that isn't a browser tab, so task-detail's nested
 * panel DnD provider keeps working untouched inside the outlet.
 *
 * The drag preview lives in a transient view store (tabReorderStore), never in
 * the domain snapshot mirror: dragover reorders the previewed *stored* order
 * within the dragged tab's pin group, the strip renders it (pills shift aside),
 * and only dragend persists — optimistically applying the final order to the
 * mirror, then `setOrder` to the host. Keeping the preview out of the mirror
 * means a concurrent server snapshot push mid-drag can't clobber it, the
 * navigation effect and app shell don't churn per dragover, and a cancel simply
 * drops the preview.
 */
export function BrowserTabsDndProvider({ children }: { children: ReactNode }) {
  const client = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  const goToTab = useGoToTab();
  /** Stored order captured at dragstart — used to skip a no-op persist. */
  const initialOrder = useRef<string[] | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  const onDragStart: DragDropEvents["dragstart"] = (event) => {
    const data = event.operation.source?.data;
    const store = useTabReorderStore.getState();
    if (isTileTabDragData(data)) {
      store.setDraggingTabId(data.tabId);
      store.setDragSource("tile");
      store.setDetached(true);
      return;
    }
    if (data?.type !== "browser-tab") return;
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (!win) return;
    const order = storedOrderIds(snapshot, win.id);
    initialOrder.current = order;
    dragStart.current = event.operation.position.current;
    store.setPreviewOrder(order);
    store.setDraggingTabId(data.tabId);
    store.setDragSource("strip");
  };

  const onDragMove: DragDropEvents["dragmove"] = (event) => {
    const start = dragStart.current;
    if (!start || !event.to) return;
    const store = useTabReorderStore.getState();
    if (store.dragSource !== "strip") return;
    const detached = exceedsDetachDistance(event.to.y - start.y);
    if (detached !== store.detached) store.setDetached(detached);
  };

  const persistOrder = (order: string[]) => {
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (!win) return;
    applyLocalTransform((s) => setTabOrder(s, win.id, order));
    void persistWrite(() =>
      client.setOrder({ windowId: win.id, tabIds: order }),
    );
  };

  const dropTileOnStrip = (tabId: string, besideTabId: string | null) => {
    useTileLayoutStore.getState().untileTab(tabId);
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (besideTabId && besideTabId !== tabId && win) {
      const order = storedOrderIds(snapshot, win.id);
      const pinnedTabIds = usePinnedTabsStore.getState().pinnedTabIds;
      const next = reorderWithinGroup(order, pinnedTabIds, tabId, besideTabId);
      if (!sameOrder(next, order)) persistOrder(next);
    }
    const tab = readMirror().tabs.find((t) => t.id === tabId);
    if (tab) goToTab(tab);
    track(ANALYTICS_EVENTS.BROWSER_TAB_UNTILED, { tile_count: 0 });
  };

  const dropTile = (tabId: string, target: unknown) => {
    if (isTileDropData(target)) {
      if (target.tabId !== tabId) tileBeside(tabId, target.tabId, target.edge);
      return;
    }
    if (isStripDropData(target)) {
      dropTileOnStrip(tabId, null);
      return;
    }
    const pill = target as { type?: unknown; tabId?: unknown } | undefined;
    if (pill?.type === "browser-tab" && typeof pill.tabId === "string") {
      dropTileOnStrip(tabId, pill.tabId);
    }
  };

  const onDragOver: DragDropEvents["dragover"] = (event) => {
    const src = event.operation.source?.data;
    const tgt = event.operation.target?.data;
    if (
      useTabReorderStore.getState().detached ||
      src?.type !== "browser-tab" ||
      tgt?.type !== "browser-tab" ||
      !src.tabId ||
      !tgt.tabId ||
      src.tabId === tgt.tabId
    ) {
      return;
    }
    const store = useTabReorderStore.getState();
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (!win) return;
    const cur = store.previewOrder ?? storedOrderIds(snapshot, win.id);
    const pinnedTabIds = usePinnedTabsStore.getState().pinnedTabIds;
    // Reorder within the dragged tab's pin group only; cross-group drags are
    // rejected (pinned pills can't land among unpinned tabs, or vice versa).
    const next = reorderWithinGroup(cur, pinnedTabIds, src.tabId, tgt.tabId);
    if (!sameOrder(next, cur)) store.setPreviewOrder(next);
  };

  const onDragEnd: DragDropEvents["dragend"] = (event) => {
    const src = event.operation.source?.data;
    const tgt = event.operation.target?.data;
    const order = useTabReorderStore.getState().previewOrder;
    const initial = initialOrder.current;
    initialOrder.current = null;
    dragStart.current = null;
    // Defer clearing the preview + persisting a frame so @dnd-kit finishes its
    // DOM cleanup first (same gotcha as the panels feature).
    requestAnimationFrame(() => {
      resetDragState();
      if (event.canceled) return;
      if (isTileTabDragData(src)) {
        dropTile(src.tabId, tgt);
        return;
      }
      if (src?.type !== "browser-tab") return;
      if (isTileDropData(tgt)) {
        tileBeside(src.tabId, tgt.tabId, tgt.edge);
        return;
      }
      if (!order || (initial && sameOrder(order, initial))) return;
      // Apply locally so the strip doesn't flit back to the mirror's pre-drop
      // order for a frame; persist through the tabsSync gate so the echo can't
      // rewind a newer write.
      persistOrder(order);
    });
  };

  return (
    <DragDropProvider
      onDragStart={onDragStart}
      onDragMove={onDragMove}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      {children}
    </DragDropProvider>
  );
}
