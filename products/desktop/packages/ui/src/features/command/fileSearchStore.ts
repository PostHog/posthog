import { create } from "zustand";

interface FileSearchState {
  /** Whether the file picker dialog is open. */
  pickerOpen: boolean;
  /** Repo-relative file shown in the new-task inline preview, or null. */
  previewFile: string | null;
  openPicker: () => void;
  closePicker: () => void;
  openPreview: (filePath: string) => void;
  closePreview: () => void;
}

/** View state for the file-search flow: picker visibility + the previewed file. */
export const useFileSearchStore = create<FileSearchState>((set) => ({
  pickerOpen: false,
  previewFile: null,
  openPicker: () => set({ pickerOpen: true }),
  closePicker: () => set({ pickerOpen: false }),
  openPreview: (filePath) => set({ previewFile: filePath }),
  closePreview: () => set({ previewFile: null }),
}));
