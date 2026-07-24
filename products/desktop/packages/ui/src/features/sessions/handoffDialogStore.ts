import type { GitFileStatus } from "@posthog/shared";
import { create } from "zustand";

type HandoffDirection = "to-local" | "to-cloud";

export interface HandoffChangedFile {
  path: string;
  status: GitFileStatus;
  linesAdded?: number;
  linesRemoved?: number;
}

interface HandoffDialogState {
  confirmOpen: boolean;
  direction: HandoffDirection | null;
  taskId: string | null;
  branchName: string | null;
  dirtyTreeOpen: boolean;
  changedFiles: HandoffChangedFile[];
  pendingAfterCommit: {
    taskId: string;
    repoPath: string;
    branchName: string | null;
  } | null;
}

interface HandoffDialogActions {
  openConfirm: (
    taskId: string,
    direction: HandoffDirection,
    branchName: string | null,
  ) => void;
  closeConfirm: () => void;
  openDirtyTreeForPendingHandoff: (
    changedFiles: HandoffChangedFile[],
    pending: {
      taskId: string;
      repoPath: string;
      branchName: string | null;
    },
  ) => void;
  hideDirtyTree: () => void;
  cancelPendingHandoff: () => void;
  clearPendingAfterCommit: () => void;
  reset: () => void;
}

type HandoffDialogStore = HandoffDialogState & HandoffDialogActions;

const initialState: HandoffDialogState = {
  confirmOpen: false,
  direction: null,
  taskId: null,
  branchName: null,
  dirtyTreeOpen: false,
  changedFiles: [],
  pendingAfterCommit: null,
};

const closedDirtyTreeState = {
  dirtyTreeOpen: false,
  changedFiles: [],
} satisfies Pick<HandoffDialogState, "dirtyTreeOpen" | "changedFiles">;

export const useHandoffDialogStore = create<HandoffDialogStore>((set) => ({
  ...initialState,
  openConfirm: (taskId, direction, branchName) =>
    set({ confirmOpen: true, taskId, direction, branchName }),
  closeConfirm: () => set({ confirmOpen: false }),
  openDirtyTreeForPendingHandoff: (changedFiles, pending) =>
    set({
      confirmOpen: false,
      dirtyTreeOpen: true,
      changedFiles,
      pendingAfterCommit: pending,
    }),
  hideDirtyTree: () => set(closedDirtyTreeState),
  cancelPendingHandoff: () =>
    set({
      ...closedDirtyTreeState,
      pendingAfterCommit: null,
    }),
  clearPendingAfterCommit: () => set({ pendingAfterCommit: null }),
  reset: () => set(initialState),
}));
