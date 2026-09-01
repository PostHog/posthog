import { create } from "zustand";

/**
 * Transient view state for an in-flight tab drag-reorder. Holds the previewed
 * *stored* order (pin-agnostic ids) so the strip can shift pills aside under
 * the cursor without touching the domain snapshot mirror — the drop is what
 * finally persists. Not persisted; cleared the moment the drag ends or cancels.
 */
interface TabReorderStore {
  previewOrder: string[] | null;
  setPreviewOrder: (order: string[] | null) => void;
}

export const useTabReorderStore = create<TabReorderStore>((set) => ({
  previewOrder: null,
  setPreviewOrder: (previewOrder) => set({ previewOrder }),
}));
