import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface CanvasViewedState {
  lastViewedAtByCanvasId: Record<string, number>;
  markCanvasViewed: (canvasId: string, at: number) => void;
}

function latestViews(
  first: Record<string, number>,
  second: Record<string, number>,
): Record<string, number> {
  const merged = { ...first };
  for (const [canvasId, viewedAt] of Object.entries(second)) {
    merged[canvasId] = Math.max(merged[canvasId] ?? 0, viewedAt);
  }
  return merged;
}

export const useCanvasViewedStore = create<CanvasViewedState>()(
  persist(
    (set) => ({
      lastViewedAtByCanvasId: {},
      markCanvasViewed: (canvasId, at) =>
        set((state) => {
          if ((state.lastViewedAtByCanvasId[canvasId] ?? 0) >= at) return state;
          return {
            lastViewedAtByCanvasId: {
              ...state.lastViewedAtByCanvasId,
              [canvasId]: at,
            },
          };
        }),
    }),
    {
      name: "canvas-viewed",
      storage: electronStorage,
      partialize: (state) => ({
        lastViewedAtByCanvasId: state.lastViewedAtByCanvasId,
      }),
      merge: (persisted, current) => ({
        ...current,
        lastViewedAtByCanvasId: latestViews(
          current.lastViewedAtByCanvasId,
          (persisted as Partial<CanvasViewedState>)?.lastViewedAtByCanvasId ??
            {},
        ),
      }),
    },
  ),
);
