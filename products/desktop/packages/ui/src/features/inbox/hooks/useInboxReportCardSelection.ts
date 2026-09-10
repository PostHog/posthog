import {
  ANALYTICS_EVENTS,
  type InboxSelectionEntryMethod,
} from "@posthog/shared/analytics-events";
import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import {
  resolveReportCardClickIntent,
  SELECTION_HOLD_MOVE_TOLERANCE_PX,
  SELECTION_HOLD_MS,
} from "@posthog/ui/features/inbox/utils/reportSelection";
import { track } from "@posthog/ui/shell/analytics";
import {
  type MouseEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

export interface InboxReportCardSelection {
  isSelected: boolean;
  /** True once anything is selected: every card then shows its checkbox and toggles on click. */
  selectionMode: boolean;
  /** Set while a hold is running, so the card suppresses text selection under the pointer. */
  isHolding: boolean;
  /** Select or deselect this report, naming the affordance the person used. */
  toggle: (method: InboxSelectionEntryMethod) => void;
  /**
   * Handlers for a wrapper around the card body. The click is handled in the capture phase,
   * because the body is a `Link` that acts on the click itself.
   */
  cardHandlers: {
    onClickCapture: (event: MouseEvent) => void;
    onPointerDown: (event: PointerEvent) => void;
    onPointerMove: (event: PointerEvent) => void;
    onPointerUp: () => void;
    onPointerLeave: () => void;
    onPointerCancel: () => void;
  };
}

/**
 * Multi-select gestures for one report card: press and hold, Cmd / Ctrl-click, shift-range, and
 * the gutter checkbox. The selection itself lives in `inboxReportSelectionStore`; this hook only
 * turns pointer events into its actions, and it does nothing at all when `enabled` is false.
 */
export function useInboxReportCardSelection(
  reportId: string,
  enabled: boolean,
): InboxReportCardSelection {
  const selectedReportIds = useInboxReportSelectionStore(
    (s) => s.selectedReportIds,
  );
  const orderedReportIds = useInboxReportSelectionStore(
    (s) => s.orderedReportIds,
  );
  const toggleReportSelection = useInboxReportSelectionStore(
    (s) => s.toggleReportSelection,
  );
  const selectRange = useInboxReportSelectionStore((s) => s.selectRange);
  const hasSelection = selectedReportIds.length > 0;

  const holdTimerRef = useRef<number | null>(null);
  const holdOriginRef = useRef<{ x: number; y: number } | null>(null);
  // A hold selects on pointerup's own click too, so that click must not also open the report.
  const suppressClickRef = useRef(false);
  const [isHolding, setIsHolding] = useState(false);

  const cancelHold = useCallback((): void => {
    if (holdTimerRef.current !== null) {
      window.clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    holdOriginRef.current = null;
    setIsHolding(false);
  }, []);
  useEffect(() => cancelHold, [cancelHold]);

  const toggle = useCallback(
    (method: InboxSelectionEntryMethod): void => {
      if (!hasSelection) {
        track(ANALYTICS_EVENTS.INBOX_SELECTION_MODE_ENTERED, {
          entry_method: method,
        });
      }
      toggleReportSelection(reportId);
    },
    [hasSelection, reportId, toggleReportSelection],
  );

  const onPointerDown = useCallback(
    (event: PointerEvent): void => {
      // A pointer that never produces a click would otherwise leave the suppression armed for
      // the next press.
      suppressClickRef.current = false;
      // Only the primary button holds; a modifier click is already a selection of its own.
      if (
        !enabled ||
        event.button !== 0 ||
        event.shiftKey ||
        event.metaKey ||
        event.ctrlKey
      ) {
        return;
      }
      // A touch client gives every contact `button === 0`, so a second finger arrives here while
      // the first hold runs. Without this the running timer loses its only reference, which means
      // no lift, no travel and no unmount can stop it from selecting the card.
      cancelHold();
      holdOriginRef.current = { x: event.clientX, y: event.clientY };
      setIsHolding(true);
      holdTimerRef.current = window.setTimeout(() => {
        holdTimerRef.current = null;
        holdOriginRef.current = null;
        setIsHolding(false);
        suppressClickRef.current = true;
        toggle("long_press");
      }, SELECTION_HOLD_MS);
    },
    [cancelHold, enabled, toggle],
  );

  const onPointerMove = useCallback(
    (event: PointerEvent): void => {
      const origin = holdOriginRef.current;
      if (!origin) {
        return;
      }
      const travelled = Math.hypot(
        event.clientX - origin.x,
        event.clientY - origin.y,
      );
      if (travelled > SELECTION_HOLD_MOVE_TOLERANCE_PX) {
        cancelHold();
      }
    },
    [cancelHold],
  );

  const onClickCapture = useCallback(
    (event: MouseEvent): void => {
      if (!enabled) {
        return;
      }
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      const intent = resolveReportCardClickIntent(event, hasSelection);
      if (intent === "open") {
        return;
      }
      // The card body is a link, so every selecting click has to stop the navigation.
      event.preventDefault();
      event.stopPropagation();
      if (intent === "range") {
        // A shift-click can open selection mode on its own, and it never goes through
        // `toggle`, so it records its own entry.
        if (!hasSelection) {
          track(ANALYTICS_EVENTS.INBOX_SELECTION_MODE_ENTERED, {
            entry_method: "shift_click",
          });
        }
        selectRange(reportId, orderedReportIds);
        return;
      }
      toggle("meta_click");
    },
    [enabled, hasSelection, orderedReportIds, reportId, selectRange, toggle],
  );

  return {
    isSelected: enabled && selectedReportIds.includes(reportId),
    selectionMode: enabled && hasSelection,
    isHolding,
    toggle,
    cardHandlers: {
      onClickCapture,
      onPointerDown,
      onPointerMove,
      onPointerUp: cancelHold,
      onPointerLeave: cancelHold,
      onPointerCancel: cancelHold,
    },
  };
}
