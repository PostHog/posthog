import { create } from "zustand";

interface PendingScrollState {
  pendingLine: Record<string, number>;
}

interface PendingScrollActions {
  requestScroll: (filePath: string, line: number) => void;
  consumeScroll: (filePath: string) => number | null;
}

type PendingScrollStore = PendingScrollState & PendingScrollActions;

export const usePendingScrollStore = create<PendingScrollStore>()(
  (set, get) => ({
    pendingLine: {},

    requestScroll: (filePath, line) =>
      set((s) => ({ pendingLine: { ...s.pendingLine, [filePath]: line } })),

    consumeScroll: (filePath) => {
      const line = get().pendingLine[filePath] ?? null;
      if (line !== null) {
        set((s) => {
          const { [filePath]: _, ...rest } = s.pendingLine;
          return { pendingLine: rest };
        });
      }
      return line;
    },
  }),
);
