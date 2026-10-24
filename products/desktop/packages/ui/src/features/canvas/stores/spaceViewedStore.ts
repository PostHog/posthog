import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SpaceViewedState {
  lastViewedAtBySpaceId: Record<string, number>;
  markSpaceViewed: (spaceId: string, at: number) => void;
}

function latestViews(
  first: Record<string, number>,
  second: Record<string, number>,
): Record<string, number> {
  const merged = { ...first };
  for (const [spaceId, viewedAt] of Object.entries(second)) {
    merged[spaceId] = Math.max(merged[spaceId] ?? 0, viewedAt);
  }
  return merged;
}

export const useSpaceViewedStore = create<SpaceViewedState>()(
  persist(
    (set) => ({
      lastViewedAtBySpaceId: {},
      markSpaceViewed: (spaceId, at) =>
        set((state) => {
          if ((state.lastViewedAtBySpaceId[spaceId] ?? 0) >= at) return state;
          return {
            lastViewedAtBySpaceId: {
              ...state.lastViewedAtBySpaceId,
              [spaceId]: at,
            },
          };
        }),
    }),
    {
      name: "space-viewed",
      storage: electronStorage,
      partialize: (state) => ({
        lastViewedAtBySpaceId: state.lastViewedAtBySpaceId,
      }),
      merge: (persisted, current) => ({
        ...current,
        lastViewedAtBySpaceId: latestViews(
          current.lastViewedAtBySpaceId,
          (persisted as Partial<SpaceViewedState>)?.lastViewedAtBySpaceId ?? {},
        ),
      }),
    },
  ),
);
