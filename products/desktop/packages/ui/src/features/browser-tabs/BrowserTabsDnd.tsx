import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { useHostTRPC } from "@posthog/host-router/react";
import { primaryWindow, setTabOrder } from "@posthog/shared";
import { useMutation } from "@tanstack/react-query";
import { type ReactNode, useRef } from "react";
import { reorderWithinGroup, storedOrderIds } from "./displayOrder";
import { usePinnedTabsStore } from "./pinnedTabsStore";
import { useTabReorderStore } from "./tabReorderStore";
import { applyLocalTransform, persistWrite } from "./tabsSync";

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
  const trpc = useHostTRPC();
  const setOrder = useMutation(trpc.browserTabs.setOrder.mutationOptions());
  /** Stored order captured at dragstart — used to skip a no-op persist. */
  const initialOrder = useRef<string[] | null>(null);

  const onDragStart: DragDropEvents["dragstart"] = (event) => {
    if (event.operation.source?.data?.type !== "browser-tab") return;
    const snapshot = browserTabsStore.getState().snapshot;
    const win = primaryWindow(snapshot);
    if (!win) return;
    const order = storedOrderIds(snapshot, win.id);
    initialOrder.current = order;
    useTabReorderStore.getState().setPreviewOrder(order);
  };

  const onDragOver: DragDropEvents["dragover"] = (event) => {
    const src = event.operation.source?.data;
    const tgt = event.operation.target?.data;
    if (
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
    const order = useTabReorderStore.getState().previewOrder;
    const initial = initialOrder.current;
    initialOrder.current = null;
    // Defer clearing the preview + persisting a frame so @dnd-kit finishes its
    // DOM cleanup first (same gotcha as the panels feature).
    requestAnimationFrame(() => {
      useTabReorderStore.getState().setPreviewOrder(null);
      if (
        event.canceled ||
        src?.type !== "browser-tab" ||
        !order ||
        (initial && sameOrder(order, initial))
      ) {
        return;
      }
      const snapshot = browserTabsStore.getState().snapshot;
      const win = primaryWindow(snapshot);
      if (!win) return;
      // Apply locally so the strip doesn't flit back to the mirror's pre-drop
      // order for a frame; persist through the tabsSync gate so the echo can't
      // rewind a newer write.
      applyLocalTransform((s) => setTabOrder(s, win.id, order));
      void persistWrite(() =>
        setOrder.mutateAsync({ windowId: win.id, tabIds: order }),
      );
    });
  };

  return (
    <DragDropProvider
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      {children}
    </DragDropProvider>
  );
}
