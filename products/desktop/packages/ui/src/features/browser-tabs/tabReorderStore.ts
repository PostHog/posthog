import { create } from "zustand";

export type TabDragSource = "strip" | "tile";

interface TabDrag {
  previewOrder: string[] | null;
  draggingTabId: string | null;
  dragSource: TabDragSource | null;
  detached: boolean;
}

interface TabReorderStore extends TabDrag {
  beginDrag: (
    drag: Omit<TabDrag, "previewOrder" | "detached"> & Partial<TabDrag>,
  ) => void;
  endDrag: () => void;
  setPreviewOrder: (order: string[] | null) => void;
  setDetached: (detached: boolean) => void;
}

const idle: TabDrag = {
  previewOrder: null,
  draggingTabId: null,
  dragSource: null,
  detached: false,
};

export const useTabReorderStore = create<TabReorderStore>((set) => ({
  ...idle,
  beginDrag: (drag) => set({ ...idle, ...drag }),
  endDrag: () => set(idle),
  setPreviewOrder: (previewOrder) => set({ previewOrder }),
  setDetached: (detached) => set({ detached }),
}));
