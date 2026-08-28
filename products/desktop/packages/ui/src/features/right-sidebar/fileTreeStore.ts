import { create } from "zustand";

interface FileTreeStoreState {
  // Per-task expanded folder paths - keyed by taskId, value is Set of expanded folder paths
  expandedPaths: Record<string, Set<string>>;
}

interface FileTreeStoreActions {
  togglePath: (taskId: string, path: string) => void;
  expandToFile: (taskId: string, filePath: string) => void;
  collapseAll: (taskId: string) => void;
}

type FileTreeStore = FileTreeStoreState & FileTreeStoreActions;

export const useFileTreeStore = create<FileTreeStore>()((set) => ({
  expandedPaths: {},
  togglePath: (taskId, path) =>
    set((state) => {
      const taskPaths = state.expandedPaths[taskId] ?? new Set<string>();
      const newPaths = new Set(taskPaths);
      if (newPaths.has(path)) {
        newPaths.delete(path);
      } else {
        newPaths.add(path);
      }
      return {
        expandedPaths: {
          ...state.expandedPaths,
          [taskId]: newPaths,
        },
      };
    }),
  expandToFile: (taskId, filePath) =>
    set((state) => {
      const taskPaths = state.expandedPaths[taskId] ?? new Set<string>();
      const newPaths = new Set(taskPaths);
      const parts = filePath.split("/");
      for (let i = 1; i < parts.length; i++) {
        newPaths.add(parts.slice(0, i).join("/"));
      }
      return {
        expandedPaths: {
          ...state.expandedPaths,
          [taskId]: newPaths,
        },
      };
    }),
  collapseAll: (taskId) =>
    set((state) => ({
      expandedPaths: {
        ...state.expandedPaths,
        [taskId]: new Set<string>(),
      },
    })),
}));

// Selector factory for checking if a path is expanded
export const selectIsPathExpanded =
  (taskId: string, path: string) => (state: FileTreeStore) =>
    state.expandedPaths[taskId]?.has(path) ?? false;
