import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import { isTextEntryTarget } from "@posthog/ui/features/inbox/utils/reportSelection";
import { useEffect, useMemo } from "react";

/**
 * List-level half of inbox multi-select: it publishes the rendered order the cards range over,
 * and it owns the Esc key. The per-card gestures live in `useInboxReportCardSelection`.
 */
export function useInboxReportListSelection(orderedReportIds: string[]) {
  const selectedReportIds = useInboxReportSelectionStore(
    (s) => s.selectedReportIds,
  );
  const clearSelection = useInboxReportSelectionStore((s) => s.clearSelection);
  const setOrderedReportIds = useInboxReportSelectionStore(
    (s) => s.setOrderedReportIds,
  );

  // Publishing the order also prunes, so a reload, a filter, a scope or a sort change drops the
  // reports that left the list before a bulk action can fire at a row nobody can see.
  useEffect(() => {
    setOrderedReportIds(orderedReportIds);
  }, [orderedReportIds, setOrderedReportIds]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isTextEntryTarget(event.target)) return;
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

  const orderedSelectedIds = useMemo(
    () => orderedReportIds.filter((id) => selectedReportIds.includes(id)),
    [orderedReportIds, selectedReportIds],
  );

  return {
    orderedSelectedIds,
    selectedCount: selectedReportIds.length,
    clearSelection,
  };
}
