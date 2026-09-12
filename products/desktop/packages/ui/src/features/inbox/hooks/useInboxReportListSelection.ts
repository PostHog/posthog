import {
  ANALYTICS_EVENTS,
  type InboxSelectionEntryMethod,
} from "@posthog/shared/analytics-events";
import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import {
  isTextEntryTarget,
  type ReportCardSelection,
  resolveReportCardClickIntent,
  SELECTION_HOLD_MOVE_TOLERANCE_PX,
  SELECTION_HOLD_MS,
} from "@posthog/ui/features/inbox/utils/reportSelection";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useMemo, useRef } from "react";

/**
 * Multi-select for an inbox list tab: press and hold, the card checkbox, Cmd or Ctrl-click, and
 * shift-range. The selection itself lives in `inboxReportSelectionStore`; this hook turns
 * gestures into its actions, keeps it pruned to the rendered rows, and clears it on Escape.
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

  const holdTimerRef = useRef<number | null>(null);
  const holdOriginRef = useRef<{ x: number; y: number } | null>(null);
  // A hold selects on pointerup's own click too, so that click must not also open the report.
  const suppressClickRef = useRef(false);

  useEffect(() => {
    pruneSelection(orderedReportIds);
  }, [orderedReportIds, pruneSelection]);

  const cancelHold = useCallback(() => {
    if (holdTimerRef.current !== null) {
      window.clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    holdOriginRef.current = null;
  }, []);
  useEffect(() => cancelHold, [cancelHold]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || isTextEntryTarget(event.target)) return;
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

  const selectedCount = selectedReportIds.length;
  const hasSelection = selectedCount > 0;

  // Recorded only for the report that opens an empty selection, which is the number that says
  // which of the affordances people find.
  const trackEntry = useCallback((method: InboxSelectionEntryMethod) => {
    if (useInboxReportSelectionStore.getState().selectedReportIds.length > 0) {
      return;
    }
    track(ANALYTICS_EVENTS.INBOX_SELECTION_MODE_ENTERED, {
      entry_method: method,
    });
  }, []);

  const getReportSelection = useCallback(
    (reportId: string): ReportCardSelection => {
      const toggle = (method: InboxSelectionEntryMethod): void => {
        trackEntry(method);
        toggleReportSelection(reportId);
      };
      return {
        isSelected: selectedReportIds.includes(reportId),
        selectionMode: hasSelection,
        toggle,
        onClick: (event) => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false;
            event.preventDefault();
            return;
          }
          const intent = resolveReportCardClickIntent(event, hasSelection);
          if (intent === "open") return;
          // The card body is a link, so every selecting click has to stop the navigation.
          event.preventDefault();
          if (intent === "range") {
            trackEntry("shift_click");
            selectRange(reportId, orderedReportIds);
            return;
          }
          toggle("meta_click");
        },
        holdHandlers: {
          onPointerDown: (event) => {
            // A press that never produces a click would otherwise leave the suppression armed
            // for the next one.
            suppressClickRef.current = false;
            // Only an unmodified primary press holds; a modifier click already selects on its own.
            if (
              event.button !== 0 ||
              event.shiftKey ||
              event.metaKey ||
              event.ctrlKey
            ) {
              return;
            }
            holdOriginRef.current = { x: event.clientX, y: event.clientY };
            holdTimerRef.current = window.setTimeout(() => {
              holdTimerRef.current = null;
              holdOriginRef.current = null;
              suppressClickRef.current = true;
              // A long press over the summary leaves the words painted as selected text.
              window.getSelection()?.removeAllRanges();
              toggle("long_press");
            }, SELECTION_HOLD_MS);
          },
          onPointerMove: (event) => {
            const origin = holdOriginRef.current;
            if (!origin) return;
            const travelled = Math.hypot(
              event.clientX - origin.x,
              event.clientY - origin.y,
            );
            if (travelled > SELECTION_HOLD_MOVE_TOLERANCE_PX) cancelHold();
          },
          onPointerUp: cancelHold,
          onPointerLeave: cancelHold,
          onPointerCancel: cancelHold,
        },
      };
    },
    [
      cancelHold,
      hasSelection,
      orderedReportIds,
      selectRange,
      selectedReportIds,
      toggleReportSelection,
      trackEntry,
    ],
  );

  const orderedSelectedIds = useMemo(
    () => orderedReportIds.filter((id) => selectedReportIds.includes(id)),
    [orderedReportIds, selectedReportIds],
  );

  return {
    orderedSelectedIds,
    selectedCount,
    getReportSelection,
    clearSelection,
  };
}
