/** How long a pointer must rest on a card before the hold selects it. */
export const SELECTION_HOLD_MS = 400;

/** A hold that travels further than this is a scroll or a drag, so it never selects. */
export const SELECTION_HOLD_MOVE_TOLERANCE_PX = 8;

/** What a click on a report card means. `open` follows the card's link to the report detail. */
export type ReportCardClickIntent = "open" | "toggle" | "range";

/**
 * A plain click opens the report until something is selected; from then on the list is in
 * selection mode and the same click toggles instead. Cmd / Ctrl always toggles, shift always
 * ranges, so a selection can start from an empty list.
 */
export function resolveReportCardClickIntent(
  modifiers: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean },
  hasSelection: boolean,
): ReportCardClickIntent {
  if (modifiers.shiftKey) {
    return "range";
  }
  if (modifiers.metaKey || modifiers.ctrlKey) {
    return "toggle";
  }
  return hasSelection ? "toggle" : "open";
}

/** True while the keyboard is in a field, where Esc belongs to the field and not to the list. */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (
    target.isContentEditable ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  ) {
    return true;
  }
  if (target instanceof HTMLInputElement) {
    return ![
      "button",
      "checkbox",
      "color",
      "file",
      "radio",
      "range",
      "reset",
      "submit",
    ].includes(target.type);
  }
  return false;
}
