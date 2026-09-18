import { create } from "zustand";

export type TabDragSource = "strip" | "tile";

/**
 * Transient view state for an in-flight tab drag. Holds the previewed *stored*
 * order (pin-agnostic ids) so the strip can shift pills aside under the cursor
 * without touching the domain snapshot mirror — the drop is what finally
 * persists. Not persisted; cleared the moment the drag ends or cancels.
 */
interface TabReorderStore {
  previewOrder: string[] | null;
  draggingTabId: string | null;
  dragSource: TabDragSource | null;
  detached: boolean;
  setPreviewOrder: (order: string[] | null) => void;
  setDraggingTabId: (tabId: string | null) => void;
  setDragSource: (source: TabDragSource | null) => void;
  setDetached: (detached: boolean) => void;
}

export const useTabReorderStore = create<TabReorderStore>((set) => ({
  previewOrder: null,
  draggingTabId: null,
  dragSource: null,
  detached: false,
  setPreviewOrder: (previewOrder) => set({ previewOrder }),
  setDraggingTabId: (draggingTabId) => set({ draggingTabId }),
  setDragSource: (dragSource) => set({ dragSource }),
  setDetached: (detached) => set({ detached }),
}));
