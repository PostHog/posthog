import { create } from "zustand";

interface AddDirectoryDialogState {
  open: boolean;
  taskId: string | null;
  path: string | null;
  onCancel: (() => void) | null;
}

interface AddDirectoryDialogActions {
  show: (params: {
    taskId: string;
    path: string;
    onCancel: () => void;
  }) => void;
  close: () => void;
}

type Store = AddDirectoryDialogState & AddDirectoryDialogActions;

export const useAddDirectoryDialogStore = create<Store>()((set) => ({
  open: false,
  taskId: null,
  path: null,
  onCancel: null,
  show: ({ taskId, path, onCancel }) =>
    set({ open: true, taskId, path, onCancel }),
  close: () => set({ open: false, taskId: null, path: null, onCancel: null }),
}));
