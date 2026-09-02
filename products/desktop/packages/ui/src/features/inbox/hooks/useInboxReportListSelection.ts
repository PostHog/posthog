import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import { type MouseEvent, useCallback, useEffect, useMemo } from "react";

/**
 * Shift/meta click selection for inbox list tabs. Plain click clears selection
 * so normal navigation proceeds on the card link.
 */
export function useInboxReportListSelection(orderedReportIds: string[]) {
  const selectedReportIds = useInboxReportSelectionStore(
    (s) => s.selectedReportIds,
  );
  const toggleReportSelection = useInboxReportSelectionStore(
    (s) => s.toggleReportSelection,
  );
  const selectRange = useInboxReportSelectionStore((s) => s.selectRange);
  const clearSelection = useInboxReportSelectionStore((s) => s.clearSelection);
  const pruneSelection = useInboxReportSelectionStore((s) => s.pruneSelection);
  const isReportSelected = useInboxReportSelectionStore(
    (s) => s.isReportSelected,
  );

  useEffect(() => {
    pruneSelection(orderedReportIds);
  }, [orderedReportIds, pruneSelection]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      if (
        useInboxReportSelectionStore.getState().selectedReportIds.length === 0
      ) {
        return;
      }
      clearSelection();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [clearSelection]);

  const handleReportClick = useCallback(
    (reportId: string, event: MouseEvent) => {
      if (event.shiftKey) {
        event.preventDefault();
        selectRange(reportId, orderedReportIds);
        return;
      }
      if (event.metaKey || event.ctrlKey) {
        event.preventDefault();
        toggleReportSelection(reportId);
        return;
      }
      clearSelection();
    },
    [clearSelection, orderedReportIds, selectRange, toggleReportSelection],
  );

  const selectedCount = selectedReportIds.length;
  const hasMultiSelection = selectedCount > 1;

  const orderedSelectedIds = useMemo(
    () => orderedReportIds.filter((id) => selectedReportIds.includes(id)),
    [orderedReportIds, selectedReportIds],
  );

  return {
    selectedReportIds,
    orderedSelectedIds,
    selectedCount,
    hasMultiSelection,
    isReportSelected,
    handleReportClick,
    clearSelection,
  };
}
