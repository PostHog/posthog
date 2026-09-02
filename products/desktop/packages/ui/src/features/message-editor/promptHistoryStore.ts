import { create } from "zustand";

interface PromptHistoryStore {
  index: number;
  savedInput: string;
  navigateUp: (history: string[], currentInput: string) => string | null;
  navigateDown: (history: string[]) => string | null;
  reset: () => void;
}

export const usePromptHistoryStore = create<PromptHistoryStore>((set, get) => ({
  index: -1,
  savedInput: "",

  navigateUp: (history, currentInput) => {
    if (history.length === 0) return null;

    const { index } = get();

    if (index === -1) {
      set({ savedInput: currentInput, index: 0 });
      return history[history.length - 1] ?? null;
    }

    if (index >= history.length - 1) return null;

    const newIndex = index + 1;
    set({ index: newIndex });
    return history[history.length - 1 - newIndex] ?? null;
  },

  navigateDown: (history) => {
    const { index, savedInput } = get();
    if (index === -1) return null;

    if (index > 0) {
      const newIndex = index - 1;
      set({ index: newIndex });
      return history[history.length - 1 - newIndex] ?? null;
    }

    set({ index: -1, savedInput: "" });
    return savedInput;
  },

  reset: () => set({ index: -1, savedInput: "" }),
}));
