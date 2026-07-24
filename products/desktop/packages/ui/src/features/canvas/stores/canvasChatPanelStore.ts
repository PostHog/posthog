import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// View state for the freeform canvas's right-hand panel — the run chat / edit
// composer dock that appears once a canvas exists or a generation is in flight.
// Collapse and width are global user preferences (persisted) so the panel keeps
// its shape across canvases and navigation.
const DEFAULT_PANEL_WIDTH = 420;

interface CanvasChatPanelState {
  collapsed: boolean;
  width: number;
  setCollapsed: (collapsed: boolean) => void;
  setWidth: (width: number) => void;
}

export const useCanvasChatPanelStore = create<CanvasChatPanelState>()(
  persist(
    (set) => ({
      collapsed: false,
      width: DEFAULT_PANEL_WIDTH,
      setCollapsed: (collapsed) => set({ collapsed }),
      setWidth: (width) => set({ width }),
    }),
    {
      name: "canvas-chat-panel-storage",
      storage: electronStorage,
      partialize: (state) => ({
        collapsed: state.collapsed,
        width: state.width,
      }),
    },
  ),
);
