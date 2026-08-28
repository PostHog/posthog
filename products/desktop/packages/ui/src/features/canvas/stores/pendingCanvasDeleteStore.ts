import { create } from "zustand";

interface PendingCanvasDeleteState {
  // Canvases the user has deleted but whose delete hasn't been sent yet — the
  // undo window. They stay in their lists, marked as deleting, and the mark
  // simply clears (nothing is recreated) if the user hits Undo. State only: the
  // timer and the eventual commit live in `deleteCanvasWithUndo`.
  pending: Record<string, boolean>;
  markPending: (dashboardId: string) => void;
  clearPending: (dashboardId: string) => void;
}

export const usePendingCanvasDeleteStore = create<PendingCanvasDeleteState>(
  (set) => ({
    pending: {},
    markPending: (dashboardId) =>
      set((s) => ({ pending: { ...s.pending, [dashboardId]: true } })),
    clearPending: (dashboardId) =>
      set((s) => {
        const { [dashboardId]: _dropped, ...rest } = s.pending;
        return { pending: rest };
      }),
  }),
);

/** True while this canvas is inside its delete-undo window. */
export function useIsCanvasPendingDelete(dashboardId: string): boolean {
  return usePendingCanvasDeleteStore((s) => !!s.pending[dashboardId]);
}
