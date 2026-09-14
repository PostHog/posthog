import type { InboxSelectionEntryMethod } from "@posthog/shared/analytics-events";
import type { MouseEvent, PointerEvent } from "react";

/** How long a pointer must rest on a card before the hold selects it. */
export const SELECTION_HOLD_MS = 400;

/** A hold that travels further than this is a scroll or a drag, so it never selects. */
export const SELECTION_HOLD_MOVE_TOLERANCE_PX = 8;

/** Multi-select wiring for one card, handed to it by the list. */
export interface ReportCardSelection {
  isSelected: boolean;
  /** True once anything is selected: every card then toggles on a plain click. */
  selectionMode: boolean;
  /** Select or deselect this report, naming the affordance the person used. */
  toggle: (method: InboxSelectionEntryMethod) => void;
  /**
   * Runs before the card's link acts on the click. It prevents the default when the click
   * selects instead of opening the report.
   */
  onClick: (event: MouseEvent) => void;
  /** Press-and-hold handlers for the card's link. */
  holdHandlers: {
    onPointerDown: (event: PointerEvent) => void;
    onPointerMove: (event: PointerEvent) => void;
    onPointerUp: () => void;
    onPointerLeave: () => void;
    onPointerCancel: () => void;
  };
}

/** What a click on a report card means. `open` follows the card's link to the report. */
export type ReportCardClickIntent = "open" | "toggle" | "range";

/**
 * A plain click opens the report until something is selected; from then on the list is in
 * selection mode and the same click toggles instead. Cmd, Ctrl and Shift always select, so a
 * selection can also start from an empty list.
 */
export function resolveReportCardClickIntent(
  modifiers: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean },
  hasSelection: boolean,
): ReportCardClickIntent {
  if (modifiers.shiftKey) return "range";
  if (modifiers.metaKey || modifiers.ctrlKey) return "toggle";
  return hasSelection ? "toggle" : "open";
}

/**
 * Click handler for a card's detail link. The selection gets the click first, and a click it
 * took never opens the report. A modifier click on a link is the browser's to answer.
 */
export function reportCardLinkClickHandler(
  selection: ReportCardSelection | undefined,
  prefetch: () => void,
): (event: MouseEvent) => void {
  return (event) => {
    selection?.onClick(event);
    if (
      event.defaultPrevented ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey
    ) {
      event.preventDefault();
      return;
    }
    prefetch();
  };
}

/** True while the keyboard is in a field, where Esc belongs to the field and not to the list. */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (
    target.isContentEditable ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  ) {
    return true;
  }
  if (target instanceof HTMLInputElement) {
    return !["button", "checkbox", "radio", "reset", "submit"].includes(
      target.type,
    );
  }
  return false;
}
