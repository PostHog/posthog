import {
  addRecentFile,
  addActionTab as coreAddActionTab,
  addTerminalTab as coreAddTerminalTab,
  closeOtherTabs as coreCloseOtherTabs,
  closeTab as coreCloseTab,
  closeTabsToRight as coreCloseTabsToRight,
  keepTab as coreKeepTab,
  moveTab as coreMoveTab,
  openReadonlyTabInSplit as coreOpenReadonlyTabInSplit,
  openTab as coreOpenTab,
  openTabInSplit as coreOpenTabInSplit,
  reorderTabs as coreReorderTabs,
  setActiveTab as coreSetActiveTab,
  updateSizes as coreUpdateSizes,
  updateTabLabel as coreUpdateTabLabel,
  updateTabMetadata as coreUpdateTabMetadata,
  createInitialTaskLayout,
  splitPanelTree,
} from "@posthog/core/panels/panelLayoutTransforms";
import { createFileTabId } from "@posthog/core/panels/panelStoreHelpers";
import { findTabInTree } from "@posthog/core/panels/panelTree";
import { ANALYTICS_EVENTS, getFileExtension } from "@posthog/shared";
import {
  createJSONStorage,
  persist,
  type StateStorage,
} from "zustand/middleware";
import { createWithEqualityFn } from "zustand/traditional";
import { track } from "../../shell/analytics";
import { updateTaskLayout } from "./panelStoreHelpers";
import type { PanelNode, Tab } from "./panelTypes";

export interface TaskLayout {
  panelTree: PanelNode;
  openFiles: string[];
  recentFiles: string[];
  draggingTabId: string | null;
  draggingTabPanelId: string | null;
  focusedPanelId: string | null;
}

export type SplitDirection = "left" | "right" | "top" | "bottom";

type TaskLayouts = Record<string, TaskLayout>;

export interface PanelLayoutStore {
  taskLayouts: TaskLayouts;

  getLayout: (taskId: string) => TaskLayout | null;
  initializeTask: (taskId: string) => void;
  openFile: (taskId: string, filePath: string, asPreview?: boolean) => void;
  openFileInSplit: (
    taskId: string,
    filePath: string,
    asPreview?: boolean,
  ) => void;
  openChannelContextInSplit: (
    taskId: string,
    context: { channelName: string | null; body: string },
  ) => void;
  openCanvasInstructionsInSplit: (
    taskId: string,
    instructions: { body: string },
  ) => void;
  openAutoresearchTab: (taskId: string) => void;
  keepTab: (taskId: string, panelId: string, tabId: string) => void;
  closeTab: (taskId: string, panelId: string, tabId: string) => void;
  closeOtherTabs: (taskId: string, panelId: string, tabId: string) => void;
  closeTabsToRight: (taskId: string, panelId: string, tabId: string) => void;
  closeTabsForFile: (taskId: string, filePath: string) => void;

  setActiveTab: (taskId: string, panelId: string, tabId: string) => void;
  setDraggingTab: (
    taskId: string,
    tabId: string | null,
    panelId: string | null,
  ) => void;
  clearDraggingTab: (taskId: string) => void;
  reorderTabs: (
    taskId: string,
    panelId: string,
    sourceIndex: number,
    targetIndex: number,
  ) => void;
  moveTab: (
    taskId: string,
    tabId: string,
    sourcePanelId: string,
    targetPanelId: string,
  ) => void;
  splitPanel: (
    taskId: string,
    tabId: string,
    sourcePanelId: string,
    targetPanelId: string,
    direction: SplitDirection,
  ) => void;
  updateSizes: (taskId: string, groupId: string, sizes: number[]) => void;
  updateTabMetadata: (
    taskId: string,
    tabId: string,
    metadata: Partial<Pick<Tab, "hasUnsavedChanges">>,
  ) => void;
  updateTabLabel: (taskId: string, tabId: string, label: string) => void;
  setFocusedPanel: (taskId: string, panelId: string) => void;
  addTerminalTab: (taskId: string, panelId: string) => void;
  addActionTab: (
    taskId: string,
    panelId: string,
    action: {
      actionId: string;
      command: string;
      cwd: string;
      label: string;
    },
  ) => void;
  clearAllLayouts: () => void;
}

const PANEL_PERSIST_DEBOUNCE_MS = 200;

/**
 * Wraps a storage so writes to the same key coalesce onto a trailing debounce.
 * Reads stay synchronous and in-memory state is untouched, so live UI is
 * unaffected; only the write to the backing store is deferred. Pending writes
 * flush on `pagehide` so the last change before the window closes isn't lost.
 */
export function createDebouncedStorage(
  base: StateStorage,
  waitMs: number,
): StateStorage {
  const pending = new Map<string, string>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  const flush = (key: string) => {
    timers.delete(key);
    const value = pending.get(key);
    pending.delete(key);
    if (value !== undefined) base.setItem(key, value);
  };

  if (typeof window !== "undefined") {
    window.addEventListener("pagehide", () => {
      for (const key of [...pending.keys()]) flush(key);
    });
  }

  return {
    getItem: (key) => base.getItem(key),
    setItem: (key, value) => {
      pending.set(key, value);
      const existing = timers.get(key);
      if (existing !== undefined) clearTimeout(existing);
      timers.set(
        key,
        setTimeout(() => flush(key), waitMs),
      );
    },
    removeItem: (key) => {
      const existing = timers.get(key);
      if (existing !== undefined) {
        clearTimeout(existing);
        timers.delete(key);
      }
      pending.delete(key);
      base.removeItem(key);
    },
  };
}

/**
 * react-resizable-panels fires a layout change every frame during a drag, and
 * persist serializes the whole layout tree on each one. Panels are uncontrolled
 * (defaultSize), so debouncing the write keeps live resize instant while
 * collapsing a drag's ~60 synchronous localStorage writes into one.
 */
const panelLayoutStorage: StateStorage = createDebouncedStorage(
  {
    getItem: (key) => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value),
    removeItem: (key) => window.localStorage.removeItem(key),
  },
  PANEL_PERSIST_DEBOUNCE_MS,
);

export const usePanelLayoutStore = createWithEqualityFn<PanelLayoutStore>()(
  persist(
    (set, get) => ({
      taskLayouts: {},

      getLayout: (taskId) => {
        return get().taskLayouts[taskId] || null;
      },

      initializeTask: (taskId) => {
        set((state) => ({
          taskLayouts: {
            ...state.taskLayouts,
            [taskId]: createInitialTaskLayout() as TaskLayout,
          },
        }));
      },

      openFile: (taskId, filePath, asPreview = true) => {
        const tabId = createFileTabId(filePath);
        set((state) =>
          updateTaskLayout(state, taskId, (layout) => {
            const updates = coreOpenTab(layout, tabId, asPreview);
            return {
              ...updates,
              recentFiles: addRecentFile(layout.recentFiles, filePath),
            } as Partial<TaskLayout>;
          }),
        );

        track(ANALYTICS_EVENTS.FILE_OPENED, {
          file_extension: getFileExtension(filePath),
          source: "sidebar",
          task_id: taskId,
        });
      },

      openFileInSplit: (taskId, filePath, asPreview = true) => {
        const tabId = createFileTabId(filePath);
        set((state) =>
          updateTaskLayout(state, taskId, (layout) => {
            const updates = coreOpenTabInSplit(layout, tabId, asPreview);
            return {
              ...updates,
              recentFiles: addRecentFile(layout.recentFiles, filePath),
            } as Partial<TaskLayout>;
          }),
        );

        track(ANALYTICS_EVENTS.FILE_OPENED, {
          file_extension: getFileExtension(filePath),
          source: "sidebar",
          task_id: taskId,
        });
      },

      openChannelContextInSplit: (taskId, context) => {
        const tabId = `context-${context.channelName ?? "channel"}`;
        const label = `${context.channelName ? `#${context.channelName} ` : ""}CONTEXT.md`;
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreOpenReadonlyTabInSplit(layout, tabId, label, {
                type: "context",
                channelName: context.channelName,
                body: context.body,
              }) as Partial<TaskLayout>,
          ),
        );
      },

      openCanvasInstructionsInSplit: (taskId, instructions) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreOpenReadonlyTabInSplit(
                layout,
                "canvas-instructions",
                "Canvas instructions",
                { type: "canvas-instructions", body: instructions.body },
              ) as Partial<TaskLayout>,
          ),
        );
      },

      openAutoresearchTab: (taskId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreOpenReadonlyTabInSplit(
                layout,
                "autoresearch",
                "Autoresearch",
                {
                  type: "autoresearch",
                },
              ) as Partial<TaskLayout>,
          ),
        );
      },

      keepTab: (taskId, panelId, tabId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreKeepTab(layout, panelId, tabId) as Partial<TaskLayout>,
          ),
        );
      },

      closeTab: (taskId, panelId, tabId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreCloseTab(layout, panelId, tabId) as Partial<TaskLayout>,
          ),
        );
      },

      closeOtherTabs: (taskId, panelId, tabId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreCloseOtherTabs(layout, panelId, tabId) as Partial<TaskLayout>,
          ),
        );
      },

      closeTabsToRight: (taskId, panelId, tabId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreCloseTabsToRight(
                layout,
                panelId,
                tabId,
              ) as Partial<TaskLayout>,
          ),
        );
      },

      closeTabsForFile: (taskId, filePath) => {
        const layout = get().taskLayouts[taskId];
        if (!layout) return;

        const tabId = createFileTabId(filePath);
        const tabLocation = findTabInTree(layout.panelTree, tabId);
        if (tabLocation) {
          get().closeTab(taskId, tabLocation.panelId, tabId);
        }
      },

      setActiveTab: (taskId, panelId, tabId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreSetActiveTab(layout, panelId, tabId) as Partial<TaskLayout>,
          ),
        );
      },

      setDraggingTab: (taskId, tabId, panelId) => {
        set((state) =>
          updateTaskLayout(state, taskId, () => ({
            draggingTabId: tabId,
            draggingTabPanelId: panelId,
          })),
        );
      },

      clearDraggingTab: (taskId) => {
        set((state) =>
          updateTaskLayout(state, taskId, () => ({
            draggingTabId: null,
            draggingTabPanelId: null,
          })),
        );
      },

      reorderTabs: (taskId, panelId, sourceIndex, targetIndex) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreReorderTabs(
                layout,
                panelId,
                sourceIndex,
                targetIndex,
              ) as Partial<TaskLayout>,
          ),
        );
      },

      moveTab: (taskId, tabId, sourcePanelId, targetPanelId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreMoveTab(
                layout,
                tabId,
                sourcePanelId,
                targetPanelId,
              ) as Partial<TaskLayout>,
          ),
        );
      },

      splitPanel: (taskId, tabId, sourcePanelId, targetPanelId, direction) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              splitPanelTree(
                layout,
                tabId,
                sourcePanelId,
                targetPanelId,
                direction,
              ) as Partial<TaskLayout>,
          ),
        );
      },

      updateSizes: (taskId, groupId, sizes) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreUpdateSizes(layout, groupId, sizes) as Partial<TaskLayout>,
          ),
        );
      },

      updateTabMetadata: (taskId, tabId, metadata) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreUpdateTabMetadata(
                layout,
                tabId,
                metadata,
              ) as Partial<TaskLayout>,
          ),
        );
      },

      updateTabLabel: (taskId, tabId, label) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreUpdateTabLabel(layout, tabId, label) as Partial<TaskLayout>,
          ),
        );
      },

      setFocusedPanel: (taskId, panelId) => {
        set((state) =>
          updateTaskLayout(state, taskId, () => ({
            focusedPanelId: panelId,
          })),
        );
      },

      addTerminalTab: (taskId, panelId) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreAddTerminalTab(layout, panelId) as Partial<TaskLayout>,
          ),
        );
      },

      addActionTab: (taskId, panelId, action) => {
        set((state) =>
          updateTaskLayout(
            state,
            taskId,
            (layout) =>
              coreAddActionTab(layout, panelId, action) as Partial<TaskLayout>,
          ),
        );
      },

      clearAllLayouts: () => {
        set({ taskLayouts: {} });
      },
    }),
    {
      name: "panel-layout-store",
      version: 10,
      migrate: () => ({ taskLayouts: {} }),
      storage: createJSONStorage(() => panelLayoutStorage),
    },
  ),
);
