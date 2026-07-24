import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const DEFAULT_PANEL_WIDTH = 360;

interface ThreadPanelState {
  openByChannel: Record<string, string | null>;
  collapsed: boolean;
  width: number;
  openThread: (
    channelId: string,
    taskId: string,
    opts?: { expand?: boolean },
  ) => void;
  closeThread: (channelId: string) => void;
  setCollapsed: (collapsed: boolean) => void;
  setWidth: (width: number) => void;
}

export const useThreadPanelStore = create<ThreadPanelState>()(
  persist(
    (set) => ({
      openByChannel: {},
      collapsed: false,
      width: DEFAULT_PANEL_WIDTH,
      openThread: (channelId, taskId, opts) =>
        set((state) => ({
          openByChannel: { ...state.openByChannel, [channelId]: taskId },
          ...(opts?.expand === false ? {} : { collapsed: false }),
        })),
      closeThread: (channelId) =>
        set((state) => ({
          openByChannel: { ...state.openByChannel, [channelId]: null },
        })),
      setCollapsed: (collapsed) => set({ collapsed }),
      setWidth: (width) => set({ width }),
    }),
    {
      name: "thread-panel-storage",
      storage: electronStorage,
      partialize: (state) => ({
        collapsed: state.collapsed,
        width: state.width,
      }),
    },
  ),
);
