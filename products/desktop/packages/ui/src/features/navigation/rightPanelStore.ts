import {
  RIGHT_PANEL_DEFAULT_WIDTH,
  RIGHT_PANEL_MIN_WIDTH,
} from "@posthog/ui/features/navigation/rightPanelGeometry";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** `changes` is also opened from elsewhere, through reviewNavigationStore. */
export type RightPanelSide = "timeline" | "artifacts" | "comments" | "changes";

/** The panel the column falls back to when it opens without a side of its own. */
export const DEFAULT_RIGHT_PANEL_SIDE: RightPanelSide = "timeline";

interface RightPanelStore {
  width: number;
  isResizing: boolean;
  /**
   * The panel each session has open. `null` is one someone closed; missing is a
   * session nobody has touched. Within-run memory, so not persisted.
   */
  sideByKey: Record<string, RightPanelSide | null | undefined>;
  /**
   * Whether untouched sessions open with the panel away. Persisted, unlike
   * `sideByKey`: putting the panel away is a standing preference.
   */
  closedByDefault: boolean;
  /**
   * Artifacts a session had when its panel last showed them, so newer ones can
   * be marked. Missing means take the current count as seen.
   */
  seenArtifactCountByKey: Record<string, number | undefined>;
  /** Which sessions have their panel out to the whole row. Within-run memory. */
  expandedByKey: Record<string, boolean | undefined>;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
  setSideForKey: (key: string, side: RightPanelSide | null) => void;
  setExpandedForKey: (key: string, expanded: boolean) => void;
  markArtifactsSeen: (key: string, count: number) => void;
}

/**
 * An open review wins - every entry point into one (command menu, PR links,
 * diff toggles) expects Changes to appear. Then an explicit choice, then the
 * default unless the panel was last put away.
 */
export function resolveRightPanelSide({
  stored,
  closedByDefault,
  isReviewOpen,
}: {
  stored: RightPanelSide | null | undefined;
  closedByDefault: boolean;
  isReviewOpen: boolean;
}): RightPanelSide | null {
  if (isReviewOpen) return "changes";
  // Review closes from elsewhere (the footer's diff chip, the shortcut) without
  // touching the panel's memory, so Changes must not outlive it.
  if (stored === "changes") return null;
  if (stored !== undefined) return stored;
  return closedByDefault ? null : DEFAULT_RIGHT_PANEL_SIDE;
}

/**
 * An undrawn session takes its whole count as seen, so an old run doesn't
 * announce its files as new. Until `ready` the count reads zero with no source
 * behind it, which must not become the baseline.
 */
export function resolveArtifactMark({
  count,
  seen,
  isShowingArtifacts,
  ready,
}: {
  count: number;
  seen: number | undefined;
  isShowingArtifacts: boolean;
  ready: boolean;
}): { markSeen: boolean; hasNew: boolean } {
  if (!ready) return { markSeen: false, hasNew: false };
  if (seen === undefined || isShowingArtifacts) {
    return { markSeen: true, hasNew: false };
  }
  return { markSeen: false, hasNew: count > seen };
}

export const useRightPanelStore = create<RightPanelStore>()(
  persist(
    (set) => ({
      width: RIGHT_PANEL_DEFAULT_WIDTH,
      isResizing: false,
      sideByKey: {},
      closedByDefault: false,
      seenArtifactCountByKey: {},
      expandedByKey: {},
      setWidth: (width) =>
        set({ width: Math.max(RIGHT_PANEL_MIN_WIDTH, width) }),
      setIsResizing: (isResizing) => set({ isResizing }),
      setSideForKey: (key, side) =>
        set((state) => ({
          sideByKey: { ...state.sideByKey, [key]: side },
          // Opening a review is not a vote on the panel, so it leaves the
          // preference where it was.
          closedByDefault: side === "changes" ? state.closedByDefault : !side,
        })),
      setExpandedForKey: (key, expanded) =>
        set((state) => ({
          expandedByKey: { ...state.expandedByKey, [key]: expanded },
        })),
      markArtifactsSeen: (key, count) =>
        set((state) =>
          state.seenArtifactCountByKey[key] === count
            ? state
            : {
                seenArtifactCountByKey: {
                  ...state.seenArtifactCountByKey,
                  [key]: count,
                },
              },
        ),
    }),
    {
      name: "right-panel",
      // Coalesces the per-pointer-event setWidth burst behind its debounce.
      storage: electronStorage,
      partialize: (state) => ({
        width: state.width,
        closedByDefault: state.closedByDefault,
      }),
    },
  ),
);
