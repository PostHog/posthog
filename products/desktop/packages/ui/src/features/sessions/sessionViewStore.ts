import { create } from "zustand";

interface SessionViewState {
  showRawLogs: boolean;
  searchQuery: string;
  showSearch: boolean;
  /**
   * Ephemeral per-tool-group expand overrides for the new thread, keyed by
   * group id. `true` = expanded, `false` = collapsed, absent = follow the
   * global collapse mode. Not persisted; wiped when the global mode changes.
   */
  groupOverrides: Record<string, boolean>;
  /**
   * Ephemeral per-task collapse of the queued-messages dock, keyed by taskId.
   * `true` = collapsed; absent/`false` = expanded (the default). Not persisted;
   * resets to expanded on app restart.
   */
  queueCollapsedByTaskId: Record<string, boolean>;
  artifactFilesCollapseByTaskId: Record<
    string,
    { collapsed: boolean; fileListKey: string }
  >;
}

interface SessionViewActions {
  setShowRawLogs: (show: boolean) => void;
  setSearchQuery: (query: string) => void;
  toggleSearch: () => void;
  setGroupOverride: (id: string, expanded: boolean) => void;
  clearGroupOverrides: () => void;
  setQueueCollapsed: (taskId: string, collapsed: boolean) => void;
  setArtifactFilesCollapsed: (
    taskId: string,
    collapsed: boolean,
    fileListKey: string,
  ) => void;
  syncArtifactFilesListKey: (taskId: string, fileListKey: string) => void;
}

type SessionViewStore = SessionViewState & { actions: SessionViewActions };

const useStore = create<SessionViewStore>((set) => ({
  showRawLogs: false,
  searchQuery: "",
  showSearch: false,
  groupOverrides: {},
  queueCollapsedByTaskId: {},
  artifactFilesCollapseByTaskId: {},
  actions: {
    setShowRawLogs: (show) => set({ showRawLogs: show }),
    setSearchQuery: (query) => set({ searchQuery: query }),
    toggleSearch: () =>
      set((state) => ({
        showSearch: !state.showSearch,
        searchQuery: state.showSearch ? "" : state.searchQuery,
      })),
    setGroupOverride: (id, expanded) =>
      set((state) => ({
        groupOverrides: { ...state.groupOverrides, [id]: expanded },
      })),
    clearGroupOverrides: () =>
      set((state) =>
        Object.keys(state.groupOverrides).length === 0
          ? state
          : { groupOverrides: {} },
      ),
    setQueueCollapsed: (taskId, collapsed) =>
      set((state) => ({
        queueCollapsedByTaskId: {
          ...state.queueCollapsedByTaskId,
          [taskId]: collapsed,
        },
      })),
    setArtifactFilesCollapsed: (taskId, collapsed, fileListKey) =>
      set((state) => ({
        artifactFilesCollapseByTaskId: {
          ...state.artifactFilesCollapseByTaskId,
          [taskId]: { collapsed, fileListKey },
        },
      })),
    syncArtifactFilesListKey: (taskId, fileListKey) =>
      set((state) => {
        const current = state.artifactFilesCollapseByTaskId[taskId];
        if (!current || current.fileListKey === fileListKey) return state;
        return {
          artifactFilesCollapseByTaskId: {
            ...state.artifactFilesCollapseByTaskId,
            [taskId]: { collapsed: false, fileListKey },
          },
        };
      }),
  },
}));

export const useShowRawLogs = () => useStore((s) => s.showRawLogs);
export const useSearchQuery = () => useStore((s) => s.searchQuery);
export const useShowSearch = () => useStore((s) => s.showSearch);
export const useGroupOverrides = () => useStore((s) => s.groupOverrides);
export const useQueueCollapsed = (taskId: string) =>
  useStore((s) => s.queueCollapsedByTaskId[taskId] ?? false);
export const useArtifactFilesCollapsed = (
  taskId: string | undefined,
  fileListKey: string | undefined,
) =>
  useStore((s) =>
    taskId === undefined
      ? false
      : (s.artifactFilesCollapseByTaskId[taskId]?.collapsed ?? false) &&
        (fileListKey === undefined ||
          s.artifactFilesCollapseByTaskId[taskId]?.fileListKey === fileListKey),
  );
export const useSessionViewActions = () => useStore((s) => s.actions);
