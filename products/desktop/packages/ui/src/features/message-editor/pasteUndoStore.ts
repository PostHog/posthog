import { create } from "zustand";

interface PasteUndoState {
  undoableChipId: string | null;
  setUndoableChipId: (chipId: string | null) => void;
}

export const usePasteUndoStore = create<PasteUndoState>((set) => ({
  undoableChipId: null,
  setUndoableChipId: (chipId) => set({ undoableChipId: chipId }),
}));
