import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const DEFAULT_PANEL_WIDTH = 360;

export type ThreadPanelTab = "timeline" | "artifacts" | "comments";

// Bumped per request so re-asking for the same tab re-applies even after the
// user has navigated away from it.
let tabRequestNonce = 0;

interface ThreadPanelState {
  openByChannel: Record<string, string | null>;
  /** Which tab the panel should land on for a task — set when a caller opens
   * the thread pointed at a specific tab (e.g. the feed's comment chip),
   * cleared by any tab-less open so a stale request can't hijack a later
   * plain open. Consumed by ActivityPanel. */
  tabRequestByTask: Record<
    string,
    { tab: ThreadPanelTab; nonce: number } | undefined
  >;
  collapsed: boolean;
  width: number;
  openThread: (
    channelId: string,
    taskId: string,
    opts?: { expand?: boolean; tab?: ThreadPanelTab },
  ) => void;
  /** Acknowledge an applied tab request. Nonce-matched so a stale ack (from a
   * panel that unmounted mid-flight) can't drop a newer request. */
  consumeTabRequest: (taskId: string, nonce: number) => void;
  closeThread: (channelId: string) => void;
  setCollapsed: (collapsed: boolean) => void;
  setWidth: (width: number) => void;
}

export const useThreadPanelStore = create<ThreadPanelState>()(
  persist(
    (set) => ({
      openByChannel: {},
      tabRequestByTask: {},
      collapsed: false,
      width: DEFAULT_PANEL_WIDTH,
      openThread: (channelId, taskId, opts) =>
        set((state) => ({
          openByChannel: { ...state.openByChannel, [channelId]: taskId },
          tabRequestByTask: {
            ...state.tabRequestByTask,
            [taskId]: opts?.tab
              ? { tab: opts.tab, nonce: ++tabRequestNonce }
              : undefined,
          },
          ...(opts?.expand === false ? {} : { collapsed: false }),
        })),
      consumeTabRequest: (taskId, nonce) =>
        set((state) =>
          state.tabRequestByTask[taskId]?.nonce === nonce
            ? {
                tabRequestByTask: {
                  ...state.tabRequestByTask,
                  [taskId]: undefined,
                },
              }
            : state,
        ),
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
