import { create } from "zustand";

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
