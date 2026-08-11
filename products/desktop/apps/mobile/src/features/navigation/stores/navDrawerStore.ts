import { create } from "zustand";
import { logger } from "@/lib/logger";

const log = logger.scope("nav-drawer");

interface NavDrawerState {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

export const useNavDrawerStore = create<NavDrawerState>((set) => ({
  isOpen: false,
  open: () => {
    log.debug("open requested");
    set({ isOpen: true });
  },
  close: () => {
    log.debug("close requested");
    set({ isOpen: false });
  },
  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
}));
