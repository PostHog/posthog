import {
  CANVAS_V2_FIELD_MAX_ENTRIES,
  CANVAS_V2_FIELD_MAX_REMOVED,
} from "@posthog/shared";

export const COPY_BOARD_LINK_ACTION = "Copy link";

export const NEW_BOARD_TEMPLATE_NAME = "Board";
export const NEW_BOARD_TEMPLATE_HINT = "Live fragments on an infinite board.";

export const DEFAULT_BOARD_NAME = "Untitled board";
export const DIALOG_CANCEL = "Cancel";

export const TOOLBAR_HISTORY = "History";
export const TOOLBAR_STATE = "State";

export const BOARD_FRAME_TITLE = "Board fragments";

/** "Duplicate 3 fragments". */
export function duplicateFragmentsAction(count: number): string {
  return `Duplicate ${fragmentCountLabel(count)}`;
}

/** "Bring 3 fragments to front". */
export function bringFragmentsToFrontAction(count: number): string {
  return `Bring ${fragmentCountLabel(count)} to front`;
}

/** "Delete 3 fragments". */
export function deleteFragmentsAction(count: number): string {
  return `Delete ${fragmentCountLabel(count)}`;
}

export const EDIT_FRAGMENT_SUBMIT = "Save fragment";

export function fragmentCodeBlockedReason(
  violations: readonly string[],
): string {
  return `${violations.join("; ")}.`;
}

/** "Last edited by Anna, 4 minutes ago". */
export function lastEditedByLabel(name: string, when: string): string {
  return `Last edited by ${name}, ${when}`;
}

/** "1 other editing", "2 others editing". */
export function collaboratorsLabel(count: number): string {
  return count === 1 ? "1 other editing" : `${count} others editing`;
}

/** "+3", for the people the faces row cannot show. */
export function presenceOverflowLabel(count: number): string {
  return `+${count}`;
}

export function STATE_USED_BY(readers: readonly string[]): string {
  if (readers.length <= 3) return `Read by ${readers.join(", ")}`;
  return `Read by ${readers.slice(0, 3).join(", ")}, and ${readers.length - 3} more`;
}

export const CHAT_EXAMPLES: readonly string[] = [
  "Add a card that counts signups this week",
  "Chart active people per day for the last 30 days",
  "Show the top five pages by views",
];

/** "3 fragments", "1 fragment". */
export function fragmentCountLabel(count: number): string {
  return count === 1 ? "1 fragment" : `${count} fragments`;
}

export const SHARED_TEXT_FULL = `This text is full. It holds ${CANVAS_V2_FIELD_MAX_ENTRIES.toLocaleString("en-US")} characters. Delete some before you write more.`;
export const SHARED_TEXT_CHANGES_FULL = `This text has ${CANVAS_V2_FIELD_MAX_REMOVED.toLocaleString("en-US")} deleted characters in it, which is the limit. Copy the text into a new fragment to go on.`;
export const SHARED_FIELD_READ_ONLY_STATE =
  "This key holds shared text. Use useSharedText or useSharedList to change it.";

export const BOARD_TOO_MANY_READS_AT_ONCE =
  "This fragment asked for too much data at once. Wait for the data it already asked for.";

export function boardReadsPausedMessage(seconds: number): string {
  return `This board is reading data too fast. Try again in ${secondsPhrase(seconds)}.`;
}

export function boardWritesPausedMessage(seconds: number): string {
  return `This board is changing shared state too fast. Try again in ${secondsPhrase(seconds)}.`;
}

function secondsPhrase(seconds: number): string {
  const whole = Math.max(1, Math.ceil(seconds));
  return whole === 1 ? "1 second" : `${whole} seconds`;
}

export const CHAT_START_ERROR = "Could not start the session";
