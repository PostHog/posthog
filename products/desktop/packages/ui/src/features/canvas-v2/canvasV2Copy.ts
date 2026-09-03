/** Every string a person reads on Canvases v2. Sentence case, plain words. */

import {
  CANVAS_V2_FIELD_MAX_ENTRIES,
  CANVAS_V2_FIELD_MAX_REMOVED,
} from "@posthog/shared";

export const CANVASES_V2_TITLE = "Canvases v2";
export const CANVASES_V2_DESCRIPTION =
  "Boards where you, your team, and the agent lay out live fragments side by side.";

export const NEW_BOARD_ACTION = "New board…";
export const RENAME_BOARD_ACTION = "Rename…";
export const DELETE_BOARD_ACTION = "Delete…";
export const BACK_TO_BOARDS_ACTION = "Back to boards";

export const BOARD_LIST_EMPTY_TITLE = "No boards yet";
export const BOARD_LIST_EMPTY_DESCRIPTION =
  "A board holds live fragments. Make one, then drag fragments in or ask the agent to add them.";
export const BOARD_LIST_ERROR_TITLE = "Could not load the boards";
export const BOARD_LIST_ERROR_DESCRIPTION =
  "Check your connection and try again.";
export const BOARD_LOAD_ERROR_TITLE = "Could not load this board";
export const BOARD_LOAD_ERROR_DESCRIPTION =
  "The board may be deleted, or the connection failed. Go back and try again.";

export const NEW_BOARD_DIALOG_TITLE = "New board";
export const NEW_BOARD_DIALOG_DESCRIPTION =
  "Give the board a name. You can change it later.";
export const RENAME_BOARD_DIALOG_TITLE = "Rename board";
export const RENAME_BOARD_DIALOG_DESCRIPTION =
  "The new name is shown to everyone on the board.";
export const BOARD_NAME_LABEL = "Name";
export const BOARD_NAME_PLACEHOLDER = "Weekly metrics";
export const DIALOG_CANCEL = "Cancel";
export const NEW_BOARD_SUBMIT = "Create board";
export const RENAME_BOARD_SUBMIT = "Save name";

export const DELETE_BOARD_TITLE = "Delete board?";
export const DELETE_BOARD_DESCRIPTION =
  "This removes the board for everyone. The chat history stays in Tasks.";
export const DELETE_BOARD_CONFIRM = "Delete board";

export const BOARD_CREATE_ERROR = "Could not create the board";
export const BOARD_RENAME_ERROR = "Could not rename the board";
export const BOARD_DELETE_ERROR = "Could not delete the board";

export const TOOLBAR_ZOOM_OUT = "Zoom out";
export const TOOLBAR_ZOOM_IN = "Zoom in";
export const TOOLBAR_FIT_TO_CONTENT = "Fit to content";
export const TOOLBAR_LIBRARY = "Library";
export const TOOLBAR_CHAT = "Chat";
export const TOOLBAR_HISTORY = "History";
export const TOOLBAR_STATE = "State";
export const TOOLBAR_ZOOM_RESET = "Reset zoom to 100%";

export const BOARD_FRAME_TITLE = "Board fragments";

export const FRAGMENT_MENU_LABEL = "Fragment actions";
export const EDIT_FRAGMENT_ACTION = "Edit code…";
export const DUPLICATE_FRAGMENT_ACTION = "Duplicate";
export const BRING_TO_FRONT_ACTION = "Bring to front";
export const DELETE_FRAGMENT_ACTION = "Delete";

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

export const EDIT_FRAGMENT_DIALOG_TITLE = "Edit fragment";
export const EDIT_FRAGMENT_DIALOG_DESCRIPTION =
  "The new code runs for everyone on the board.";
export const FRAGMENT_TITLE_LABEL = "Title";
export const FRAGMENT_TITLE_PLACEHOLDER = "Signups this week";
export const FRAGMENT_CODE_LABEL = "Code";
export const EDIT_FRAGMENT_SUBMIT = "Save fragment";

/** "Last edited by Anna, 4 minutes ago". */
export function lastEditedByLabel(name: string, when: string): string {
  return `Last edited by ${name}, ${when}`;
}

export const SYNC_SYNCED = "Synced";
export const SYNC_SAVING = "Saving…";
export const SYNC_OFFLINE = "Offline. Changes are saved when you reconnect.";
export const SYNC_LOADING = "Loading…";
export const SYNC_ERROR = "Could not sync the board";

/** "1 other editing", "2 others editing". */
export function collaboratorsLabel(count: number): string {
  return count === 1 ? "1 other editing" : `${count} others editing`;
}

export const PRESENCE_FACES_LABEL = "People on this board";
export const PRESENCE_UNKNOWN_NAME = "Someone";

/** "+3", for the people the faces row cannot show. */
export function presenceOverflowLabel(count: number): string {
  return `+${count}`;
}

export const HISTORY_PANEL_CLOSE = "Close history";
export const HISTORY_LOADING = "Loading the rest of the history…";
export const HISTORY_EMPTY = "No changes yet.";
export const HISTORY_RESTORE_ACTION = "Restore to here";
export const HISTORY_RESTORE_CONFIRM = "Restore board";
export const HISTORY_ACTOR_AGENT = "Agent";
export const HISTORY_ACTOR_UNKNOWN = "Someone";
export const HISTORY_ACTOR_YOU = "you";

export const STATE_PANEL_CLOSE = "Close state";
export const STATE_EMPTY = "No shared state yet.";

export const BOARD_EMPTY_HINT =
  "Drag a fragment from the library or ask the agent to add one.";
export const CHAT_PLACEHOLDER =
  "Describe what you want on this board. The agent adds fragments as it works.";
export const HISTORY_RESTORE_TITLE = "Restore the board to this point?";
export const HISTORY_RESTORE_DESCRIPTION =
  "This adds a new change. Nothing in the history is lost.";

/** "3 fragments", "1 fragment". */
export function fragmentCountLabel(count: number): string {
  return count === 1 ? "1 fragment" : `${count} fragments`;
}

export const LIBRARY_PANEL_TITLE = "Library";
export const LIBRARY_PANEL_CLOSE = "Close library";
export const LIBRARY_PANEL_HINT =
  "Drag a fragment onto the board, or click to add it.";

export const SHARED_TEXT_FULL = `This text is full. It holds ${CANVAS_V2_FIELD_MAX_ENTRIES.toLocaleString("en-US")} characters. Delete some before you write more.`;
export const SHARED_TEXT_CHANGES_FULL = `This text has ${CANVAS_V2_FIELD_MAX_REMOVED.toLocaleString("en-US")} deleted characters in it, which is the limit. Copy the text into a new fragment to go on.`;
export const SHARED_FIELD_READ_ONLY_STATE =
  "This key holds shared text. Use useSharedText or useSharedList to change it.";

export const CHAT_PANEL_TITLE = "Chat";
export const CHAT_PANEL_CLOSE = "Close chat";
export const CHAT_START_ACTION = "Start";
export const CHAT_NEW_SESSION_ACTION = "New session";
export const CHAT_START_ERROR = "Could not start the session";
