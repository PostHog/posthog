import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { useService } from "@posthog/di/react";
import { primaryWindow, setTabOrder } from "@posthog/shared";
import { isTileDropData } from "@posthog/ui/features/tab-tiling/TileDropZones";
import {
  tileBeside,
  untileTracked,
} from "@posthog/ui/features/tab-tiling/tileActions";
import { isTileTabDragData } from "@posthog/ui/features/tab-tiling/tileDrag";
import { useTileLayoutStore } from "@posthog/ui/features/tab-tiling/tileLayoutStore";
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
import { isBrowserTabDragData, stripTarget } from "./stripDrop";
import { exceedsDetachDistance } from "./tabDetach";
import { useTabReorderStore } from "./tabReorderStore";
import { applyLocalTransform, persistWrite, readMirror } from "./tabsSync";
import { useGoToTab } from "./useGoToTab";

function sameOrder(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, i) => id === b[i]);
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

  const currentOrder = () => {
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    return win ? storedOrderIds(snapshot, win.id) : null;
  };

  const onDragStart: DragDropEvents["dragstart"] = (event) => {
    const data = event.operation.source?.data;
    const store = useTabReorderStore.getState();
    if (isTileTabDragData(data)) {
      store.beginDrag({
        draggingTabId: data.tabId,
        dragSource: "tile",
        detached: true,
      });
      return;
    }
    if (!isBrowserTabDragData(data)) return;
    const order = currentOrder();
    if (!order) return;
    initialOrder.current = order;
    dragStart.current = event.operation.position.current;
    store.beginDrag({
      draggingTabId: data.tabId,
      dragSource: "strip",
      previewOrder: order,
    });
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
    untileTracked(tabId);
    const order = currentOrder();
    if (previewed && order && !sameOrder(previewed, order)) {
      persistOrder(previewed);
    }
    const tab = readMirror().tabs.find((t) => t.id === tabId);
    if (tab) goToTab(tab);
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
    if (stripTarget(target)) dropTileOnStrip(tabId, previewed);
  };

  const previewTileOverStrip = (tabId: string, target: unknown) => {
    const store = useTabReorderStore.getState();
    const strip = stripTarget(target);
    if (!strip) {
      if (store.previewOrder) store.setPreviewOrder(null);
      return;
    }
    const cur = store.previewOrder ?? currentOrder();
    if (!cur) return;
    if (!strip.pillId || strip.pillId === tabId) {
      if (!store.previewOrder) store.setPreviewOrder(cur);
      return;
    }
    const pinnedTabIds = usePinnedTabsStore.getState().pinnedTabIds;
    const next = reorderWithinGroup(cur, pinnedTabIds, tabId, strip.pillId);
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
    const store = useTabReorderStore.getState();
    if (
      store.detached ||
      !isBrowserTabDragData(src) ||
      !isBrowserTabDragData(tgt) ||
      src.tabId === tgt.tabId
    ) {
      return;
    }
    const cur = store.previewOrder ?? currentOrder();
    if (!cur) return;
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
      useTabReorderStore.getState().endDrag();
      if (event.canceled) return;
      if (isTileTabDragData(src)) {
        dropTile(src.tabId, tgt, order);
        return;
      }
      if (!isBrowserTabDragData(src)) return;
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
