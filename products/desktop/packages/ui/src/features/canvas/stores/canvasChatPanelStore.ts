import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// View state for the freeform canvas's right-hand panel — the run chat / edit
// composer dock that appears once a canvas exists or a generation is in flight.
// Collapse and width are global user preferences (persisted) so the panel keeps
// its shape across canvases and navigation.
const DEFAULT_PANEL_WIDTH = 420;
export type CanvasPanelTab = "chat" | "comments";

interface CanvasChatPanelState {
  collapsed: boolean;
  width: number;
  tab: CanvasPanelTab;
  /** Whether the dock was opened while viewing (rather than editing) a canvas.
   * View mode has no other reason to keep it mounted, so this — not the active
   * tab — is what holds it open there, and a tab switch leaves it alone. */
  viewOpen: boolean;
  setCollapsed: (collapsed: boolean) => void;
  setWidth: (width: number) => void;
  setTab: (tab: CanvasPanelTab) => void;
  openChat: () => void;
  openComments: () => void;
}

export const useCanvasChatPanelStore = create<CanvasChatPanelState>()(
  persist(
    (set) => ({
      collapsed: false,
      width: DEFAULT_PANEL_WIDTH,
      tab: "chat",
      viewOpen: false,
      // Minimizing in view mode dismisses the dock entirely: there's no rail
      // button there, so the way back is the breadcrumb's Comments button.
      setCollapsed: (collapsed) =>
        set(collapsed ? { collapsed, viewOpen: false } : { collapsed }),
      setWidth: (width) => set({ width }),
      setTab: (tab) => set({ tab }),
      openChat: () => set({ collapsed: false, tab: "chat", viewOpen: false }),
      openComments: () =>
        set({ collapsed: false, tab: "comments", viewOpen: true }),
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
