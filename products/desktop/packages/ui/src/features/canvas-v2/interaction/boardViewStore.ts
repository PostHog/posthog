import { create } from "zustand";

/**
 * What the person has open and selected on the board they are looking at. All
 * of it is view state for this window, so none of it is persisted or synced.
 */
interface BoardViewState {
  selectedId: string | null;
  paletteOpen: boolean;
  chatOpen: boolean;
  historyOpen: boolean;
  inspectorOpen: boolean;
  /** Fragments a history group touched. Drawn with a ring, never moved into view. */
  highlightedIds: string[];
  setSelectedId: (id: string | null) => void;
  setPaletteOpen: (open: boolean) => void;
  setChatOpen: (open: boolean) => void;
  setHistoryOpen: (open: boolean) => void;
  setInspectorOpen: (open: boolean) => void;
  setHighlightedIds: (ids: string[]) => void;
  togglePalette: () => void;
  toggleChat: () => void;
  toggleHistory: () => void;
  toggleInspector: () => void;
  reset: () => void;
}

const INITIAL = {
  selectedId: null,
  paletteOpen: false,
  chatOpen: false,
  historyOpen: false,
  inspectorOpen: false,
  highlightedIds: [] as string[],
};

export const useBoardViewStore = create<BoardViewState>()((set) => ({
  ...INITIAL,
  setSelectedId: (selectedId) => set({ selectedId }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
  setHighlightedIds: (highlightedIds) => set({ highlightedIds }),
  togglePalette: () => set((state) => ({ paletteOpen: !state.paletteOpen })),
  toggleChat: () => set((state) => ({ chatOpen: !state.chatOpen })),
  toggleHistory: () => set((state) => ({ historyOpen: !state.historyOpen })),
  toggleInspector: () =>
    set((state) => ({ inspectorOpen: !state.inspectorOpen })),
  reset: () => set({ ...INITIAL }),
}));

export function useBoardSelectedId(): string | null {
  return useBoardViewStore((state) => state.selectedId);
}

export function useBoardHighlightedIds(): string[] {
  return useBoardViewStore((state) => state.highlightedIds);
}

export function useBoardPaletteOpen(): boolean {
  return useBoardViewStore((state) => state.paletteOpen);
}

export function useBoardChatOpen(): boolean {
  return useBoardViewStore((state) => state.chatOpen);
}

export function useBoardHistoryOpen(): boolean {
  return useBoardViewStore((state) => state.historyOpen);
}

export function useBoardInspectorOpen(): boolean {
  return useBoardViewStore((state) => state.inspectorOpen);
}

/** Non-React writer, for callbacks outside the tree. */
export function selectBoardFragment(id: string | null): void {
  useBoardViewStore.getState().setSelectedId(id);
}

/** Non-React writer, so a closing board leaves no stale selection. */
export function resetBoardView(): void {
  useBoardViewStore.getState().reset();
}
