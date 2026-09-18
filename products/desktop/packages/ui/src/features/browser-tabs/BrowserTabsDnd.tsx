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
import {
  keepGroupTogether,
  reorderWithinGroup,
  storedOrderIds,
} from "./displayOrder";
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
  store.setOverStrip(false);
}

function tileBeside(
  tabId: string,
  targetTabId: string,
  edge: TileEdge,
  source: "strip" | "tile",
): void {
  useTileLayoutStore.getState().tileTab(tabId, targetTabId, edge);
  const group = groupForTab(useTileLayoutStore.getState().groups, targetTabId);
  track(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
    edge,
    source,
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

  const dropTileOnStrip = (tabId: string, previewed: string[] | null) => {
    const before = groupForTab(useTileLayoutStore.getState().groups, tabId);
    const remaining = before ? tabIdsIn(before.root).length - 1 : 0;
    useTileLayoutStore.getState().untileTab(tabId);
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (previewed && win) {
      const order = storedOrderIds(snapshot, win.id);
      if (!sameOrder(previewed, order)) persistOrder(previewed);
    }
    const tab = readMirror().tabs.find((t) => t.id === tabId);
    if (tab) goToTab(tab);
    track(ANALYTICS_EVENTS.BROWSER_TAB_UNTILED, {
      tile_count: remaining > 1 ? remaining : 0,
    });
  };

  const dropTile = (
    tabId: string,
    target: unknown,
    previewed: string[] | null,
  ) => {
    if (isTileDropData(target)) {
      if (target.tabId !== tabId) {
        tileBeside(tabId, target.tabId, target.edge, "tile");
      }
      return;
    }
    const pill = target as { type?: unknown } | undefined;
    if (isStripDropData(target) || pill?.type === "browser-tab") {
      dropTileOnStrip(tabId, previewed);
    }
  };

  const previewTileOverStrip = (tabId: string, target: unknown) => {
    const store = useTabReorderStore.getState();
    const pill = target as { type?: unknown; tabId?: unknown } | undefined;
    const pillId = pill?.type === "browser-tab" ? pill.tabId : undefined;
    const onStrip = typeof pillId === "string" || isStripDropData(target);
    store.setOverStrip(onStrip);
    if (!onStrip) {
      if (store.previewOrder) store.setPreviewOrder(null);
      return;
    }
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (!win) return;
    const cur = store.previewOrder ?? storedOrderIds(snapshot, win.id);
    if (typeof pillId !== "string" || pillId === tabId) {
      if (!store.previewOrder) store.setPreviewOrder(cur);
      return;
    }
    const pinnedTabIds = usePinnedTabsStore.getState().pinnedTabIds;
    const next = reorderWithinGroup(cur, pinnedTabIds, tabId, pillId);
    if (!sameOrder(next, cur) || !store.previewOrder) {
      store.setPreviewOrder(next);
    }
  };

  const onDragOver: DragDropEvents["dragover"] = (event) => {
    const src = event.operation.source?.data;
    const tgt = event.operation.target?.data;
    if (isTileTabDragData(src)) {
      previewTileOverStrip(src.tabId, tgt);
      return;
    }
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
    const next = keepGroupTogether(
      reorderWithinGroup(cur, pinnedTabIds, src.tabId, tgt.tabId),
      useTileLayoutStore.getState().groups,
      src.tabId,
    );
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
        dropTile(src.tabId, tgt, order);
        return;
      }
      if (src?.type !== "browser-tab") return;
      if (isTileDropData(tgt)) {
        tileBeside(src.tabId, tgt.tabId, tgt.edge, "strip");
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
