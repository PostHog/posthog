import { create } from "zustand";

interface InboxReportSelectionState {
  selectedReportIds: string[];
  /** The last report ID that was clicked – used as the anchor for shift-click range selection. */
  lastClickedId: string | null;
}

interface InboxReportSelectionActions {
  /** Replace the entire selection (plain click). */
  setSelectedReportIds: (reportIds: string[]) => void;
  /** Toggle a single report in/out of the selection (cmd-click / checkbox). */
  toggleReportSelection: (reportId: string) => void;
  /** Select a contiguous range from the last-clicked report to `toId` within the given ordered list.
   *  Existing selection outside the range is preserved (shift-click behavior). */
  selectRange: (toId: string, orderedIds: string[]) => void;
  /** Select exactly the contiguous range from `anchorId` to `toId`, replacing the entire selection.
   *  Unlike `selectRange`, this does not merge with existing selection – used for Shift+Arrow keyboard navigation. */
  selectExactRange: (
    anchorId: string,
    toId: string,
    orderedIds: string[],
  ) => void;
  isReportSelected: (reportId: string) => boolean;
  clearSelection: () => void;
  /** Remove a set of ids from the selection (used after a partial-success bulk action). */
  removeFromSelection: (reportIds: string[]) => void;
  pruneSelection: (visibleReportIds: string[]) => void;
}

type InboxReportSelectionStore = InboxReportSelectionState &
  InboxReportSelectionActions;

export const useInboxReportSelectionStore = create<InboxReportSelectionStore>()(
  (set, get) => ({
    selectedReportIds: [],
    lastClickedId: null,

    setSelectedReportIds: (reportIds) =>
      set({
        selectedReportIds: Array.from(new Set(reportIds)),
        lastClickedId:
          reportIds.length === 1 ? reportIds[0] : get().lastClickedId,
      }),

    toggleReportSelection: (reportId) =>
      set((state) => {
        const isRemoving = state.selectedReportIds.includes(reportId);
        return {
          selectedReportIds: isRemoving
            ? state.selectedReportIds.filter((id) => id !== reportId)
            : [...state.selectedReportIds, reportId],
          lastClickedId: reportId,
        };
      }),

    selectRange: (toId, orderedIds) =>
      set((state) => {
        const anchorId = state.lastClickedId;
        if (!anchorId) {
          // No anchor – just select the target
          return { selectedReportIds: [toId], lastClickedId: toId };
        }
        const anchorIndex = orderedIds.indexOf(anchorId);
        const toIndex = orderedIds.indexOf(toId);
        if (anchorIndex === -1 || toIndex === -1) {
          return { selectedReportIds: [toId], lastClickedId: toId };
        }
        const start = Math.min(anchorIndex, toIndex);
        const end = Math.max(anchorIndex, toIndex);
        const rangeIds = orderedIds.slice(start, end + 1);
        // Merge with existing selection (standard shift-click behavior)
        const merged = Array.from(
          new Set([...state.selectedReportIds, ...rangeIds]),
        );
        return { selectedReportIds: merged, lastClickedId: toId };
      }),

    selectExactRange: (anchorId, toId, orderedIds) =>
      set(() => {
        const anchorIndex = orderedIds.indexOf(anchorId);
        const toIndex = orderedIds.indexOf(toId);
        if (anchorIndex === -1 || toIndex === -1) {
          return { selectedReportIds: [toId], lastClickedId: toId };
        }
        const start = Math.min(anchorIndex, toIndex);
        const end = Math.max(anchorIndex, toIndex);
        const rangeIds = orderedIds.slice(start, end + 1);
        // Keep lastClickedId as the anchor – the caller manages cursor position
        return { selectedReportIds: rangeIds, lastClickedId: anchorId };
      }),

    isReportSelected: (reportId) => get().selectedReportIds.includes(reportId),

    clearSelection: () => set({ selectedReportIds: [], lastClickedId: null }),

    removeFromSelection: (reportIds) => {
      if (reportIds.length === 0) return;
      const toRemove = new Set(reportIds);
      set((state) => ({
        selectedReportIds: state.selectedReportIds.filter(
          (id) => !toRemove.has(id),
        ),
        lastClickedId:
          state.lastClickedId && toRemove.has(state.lastClickedId)
            ? null
            : state.lastClickedId,
      }));
    },

    pruneSelection: (visibleReportIds) => {
      const visibleIds = new Set(visibleReportIds);
      set((state) => ({
        selectedReportIds: state.selectedReportIds.filter((id) =>
          visibleIds.has(id),
        ),
      }));
    },
  }),
);
