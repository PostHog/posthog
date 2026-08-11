import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { RightPanelSide } from "./navPanelStore";

export const RIGHT_PANEL_MIN_WIDTH = 280;
const RIGHT_PANEL_DEFAULT_WIDTH = 340;

interface RightPanelStore {
  width: number;
  isResizing: boolean;
  /**
   * The panel each session (or the sessionless fallback key) had open, so
   * switching back to a session restores its panel. Not persisted — this is
   * within-run memory; a fresh launch starts with panels closed.
   */
  sideByKey: Record<string, RightPanelSide | undefined>;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
  setSideForKey: (key: string, side: RightPanelSide | undefined) => void;
}

export const useRightPanelStore = create<RightPanelStore>()(
  persist(
    (set) => ({
      width: RIGHT_PANEL_DEFAULT_WIDTH,
      isResizing: false,
      sideByKey: {},
      setWidth: (width) =>
        set({ width: Math.max(RIGHT_PANEL_MIN_WIDTH, width) }),
      setIsResizing: (isResizing) => set({ isResizing }),
      setSideForKey: (key, side) =>
        set((state) => ({ sideByKey: { ...state.sideByKey, [key]: side } })),
    }),
    {
      name: "right-panel",
      partialize: (state) => ({ width: state.width }),
      merge: (persisted, current) => {
        const stored = (persisted ?? {}) as Partial<
          Pick<RightPanelStore, "width">
        >;
        return {
          ...current,
          width: Math.max(RIGHT_PANEL_MIN_WIDTH, stored.width ?? current.width),
        };
      },
    },
  ),
);
