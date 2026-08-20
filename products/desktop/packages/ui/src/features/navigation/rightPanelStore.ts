import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which panel the right column shows. `changes` is also opened from elsewhere,
 * through reviewNavigationStore.
 */
export type RightPanelSide = "timeline" | "artifacts" | "comments" | "changes";

/** The panel the column falls back to when it opens without a side of its own. */
export const DEFAULT_RIGHT_PANEL_SIDE: RightPanelSide = "timeline";

export const RIGHT_PANEL_MIN_WIDTH = 280;
const RIGHT_PANEL_DEFAULT_WIDTH = 340;

/**
 * The most of its row the panel pushes the content pane out of before it starts
 * covering it instead. Past this the pane is as narrow as it is going to get, so
 * the panel keeps widening over the top of a pane that no longer reflows - which
 * is what makes expanding cheap, and what keeps the line where the two behaviors
 * meet from being a jump.
 */
export const PANEL_PUSH_MAX_SHARE = 0.5;

/**
 * What the panel always leaves of the row rather than taking all of it, whether
 * it got there by being expanded or by being dragged. A sliver of the pane still
 * showing is what says the panel is over the content and not a page of its own,
 * and it gives somewhere to click back to.
 */
export const PANEL_ROW_INSET_PX = 50;

interface RightPanelStore {
  width: number;
  isResizing: boolean;
  /**
   * The panel each session (or the sessionless fallback key) has open, so
   * coming back to a session finds it as it was left. `null` is a panel someone
   * closed; a missing entry is a session nobody has touched, which falls back to
   * `closedByDefault`. Not persisted, because this is within-run memory.
   */
  sideByKey: Record<string, RightPanelSide | null | undefined>;
  /**
   * Whether a session nobody has touched opens with its panel away, following
   * whichever someone did last: closing one turns this on, opening one turns it
   * back off. Persisted, unlike `sideByKey`, because putting the panel away is a
   * standing preference rather than a fact about one session - someone working
   * in a narrow window closes it once and expects the sessions they open after
   * that, this run and the next, to leave the width to the content.
   */
  closedByDefault: boolean;
  /**
   * How many artifacts a session had the last time its panel showed them, so
   * the switcher can mark the ones that arrived since. A missing entry is a
   * session nobody has drawn yet, which takes whatever it already has as seen:
   * opening an old session is not news. Not persisted, for the same reason
   * `sideByKey` isn't - this is within-run memory.
   */
  seenArtifactCountByKey: Record<string, number | undefined>;
  /**
   * Which sessions have their panel expanded to the whole content row. Not
   * persisted, for the same reason `sideByKey` isn't - this is within-run
   * memory.
   */
  expandedByKey: Record<string, boolean | undefined>;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
  setSideForKey: (key: string, side: RightPanelSide | null) => void;
  setExpandedForKey: (key: string, expanded: boolean) => void;
  markArtifactsSeen: (key: string, count: number) => void;
}

/**
 * Which panel a session shows, given what it was left on. An open review mode
 * wins, because every existing "open review" entry point (the command menu, PR
 * links, diff toggles) sets it and expects the changes to appear; then an
 * explicit choice, including the `null` of a panel someone closed; then the
 * timeline, unless the last thing anyone did to a panel was put it away, in
 * which case a session opens leaving the width to its content.
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
  // The review mode has the last word on Changes in both directions. Whoever
  // closes a review closes it from wherever they are (the footer's diff chip,
  // the review shortcut) without touching the panel's own memory, and a panel
  // that kept showing Changes there would draw its title over a review that
  // has dropped its queries.
  if (stored === "changes") return null;
  if (stored !== undefined) return stored;
  return closedByDefault ? null : DEFAULT_RIGHT_PANEL_SIDE;
}

/**
 * What a session's switcher does with the artifact count it just read: whether
 * to take this count as seen, and whether to mark the button.
 *
 * A session nobody has drawn yet (`seen` undefined) takes its whole count as
 * seen, so opening a run that finished last week doesn't announce its files as
 * new. A panel already showing artifacts keeps up with them, so the mark can
 * never appear behind an open list.
 *
 * Until `ready`, the count has no manifest source behind it and reads as zero.
 * Taking that zero as seen would make the real files look new the moment they
 * load, so an unready count is neither taken as seen nor allowed to mark.
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

/**
 * How wide the panel is allowed to be: what it was dragged to, held to its own
 * floor and to the row's ceiling. A width dragged out on a wide monitor still
 * fits when the app is opened on a narrow one, and a row with less room than the
 * floor asks for gives what it has rather than overflowing.
 */
export function resolvePanelWidth(stored: number, rowWidth: number): number {
  const ceiling = Math.max(0, rowWidth - PANEL_ROW_INSET_PX);
  return Math.max(
    Math.min(RIGHT_PANEL_MIN_WIDTH, ceiling),
    Math.min(stored, ceiling),
  );
}

/**
 * Dragging the grip past the panel's floor toward the edge closes it, and while
 * the button is still held, dragging back out brings it in again. The reopen
 * line sits outside the close line so the boundary can't jitter.
 */
const DRAG_CLOSE_AT = RIGHT_PANEL_MIN_WIDTH * 0.5;
const DRAG_REOPEN_AT = DRAG_CLOSE_AT + 16;

/** What a drag is asking of the panel, given where the pointer has reached. */
export type PanelDrag =
  | { action: "resize"; width: number }
  /** Out of the full row and back to a width of its own, mid-drag. */
  | { action: "collapse"; width: number }
  | { action: "close" }
  | { action: "reopen"; width: number }
  /** The pointer is somewhere the panel has no answer for. */
  | { action: "hold" };

/**
 * What the pointer's distance from the row's right edge means to the panel it
 * is dragging. Expanded, the panel is already as wide as the row allows, so
 * dragging out asks for nothing it can have and dragging in is how expanding
 * comes undone - from there the drag carries on as an ordinary one.
 */
export function resolvePanelDrag({
  pointer,
  rowWidth,
  open,
  expanded,
}: {
  /** The pointer's distance from the row's right edge. */
  pointer: number;
  rowWidth: number;
  open: boolean;
  expanded: boolean;
}): PanelDrag {
  const width = resolvePanelWidth(pointer, rowWidth);

  if (expanded) {
    return width >= resolvePanelWidth(rowWidth, rowWidth)
      ? { action: "hold" }
      : { action: "collapse", width };
  }
  if (open) {
    return pointer < DRAG_CLOSE_AT
      ? { action: "close" }
      : { action: "resize", width };
  }
  return pointer >= DRAG_REOPEN_AT
    ? { action: "reopen", width }
    : { action: "hold" };
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
          // Opening a review is not a vote on the panel: PR links and diff
          // toggles open Changes without anyone reaching for the column, and
          // resolving refuses to carry Changes into a session with no review
          // open anyway. So a review leaves the preference where it was.
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
      // A resize drag calls setWidth per pointer event, and this backend
      // coalesces the burst behind its debounce instead of writing
      // synchronously on each one, the way every other panel store does.
      storage: electronStorage,
      partialize: (state) => ({
        width: state.width,
        closedByDefault: state.closedByDefault,
      }),
    },
  ),
);
