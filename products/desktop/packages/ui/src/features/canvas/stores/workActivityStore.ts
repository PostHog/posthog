import { create } from "zustand";

/**
 * Whether the Work layout's Activity column (the notification center) is
 * showing. View state, not a route: it slides over the Work column and leaves
 * the tab you are reading where it is.
 */
interface WorkActivityState {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const useWorkActivityStore = create<WorkActivityState>()((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set((state) => ({ open: !state.open })),
}));

export function closeWorkActivity(): void {
  useWorkActivityStore.getState().setOpen(false);
}
