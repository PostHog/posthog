import { isMac } from "@posthog/ui/utils/platform";

export function panelTabShortcut(macPlatform: boolean): string {
  const modifier = macPlatform ? "ctrl" : "alt";
  return Array.from(
    { length: 9 },
    (_, index) => `${modifier}+${index + 1}`,
  ).join(",");
}

export const SHORTCUTS = {
  COMMAND_MENU: "mod+k",
  NEW_TASK: "mod+n",
  NEW_TAB: "mod+t",
  SETTINGS: "mod+,",
  SHORTCUTS_SHEET: "mod+/",
  GO_BACK: "mod+[",
  GO_FORWARD: "mod+]",
  // Arrow variants must stay outside form fields/editors, where mod+left/right
  // means jump to line start/end - bind them without enableOnFormTags.
  GO_BACK_ALT: "mod+left",
  GO_FORWARD_ALT: "mod+right",
  TOGGLE_LEFT_SIDEBAR: "mod+b",
  TOGGLE_ACTIVITY_PANEL: "mod+alt+b",
  TOGGLE_REVIEW_PANEL: "mod+shift+b",
  PREV_TASK: "mod+shift+[,ctrl+shift+tab",
  NEXT_TASK: "mod+shift+],ctrl+tab",
  ARCHIVE_TASK: "mod+shift+a",
  CLOSE_TAB: "mod+w",
  SWITCH_TAB: panelTabShortcut(isMac),
  SWITCH_TASK: "mod+1,mod+2,mod+3,mod+4,mod+5,mod+6,mod+7,mod+8,mod+9",
  // No mod+0: the Electron View menu owns CmdOrCtrl+0 for "Actual Size", and a
  // renderer preventDefault can't reliably beat a main-process accelerator. The
  // personal space takes slot 1 instead.
  SWITCH_STARRED_CHANNEL:
    "mod+1,mod+2,mod+3,mod+4,mod+5,mod+6,mod+7,mod+8,mod+9",
  // Same keys as SWITCH_STARRED_CHANNEL / SWITCH_TASK, claimed by the tab strip
  // wherever it is shown; those two are disabled there so the keys have one
  // owner at a time.
  SWITCH_BROWSER_TAB: "mod+1,mod+2,mod+3,mod+4,mod+5,mod+6,mod+7,mod+8,mod+9",
  FOCUS_SPACE_SEARCH: "mod+shift+s",
  TOGGLE_FOCUS: "mod+r",
  PASTE_AS_FILE: "mod+shift+v",
  INBOX: "mod+i",
  SPACE_UP: "mod+up",
  SPACE_DOWN: "mod+down",
  FIND_IN_CONVERSATION: "mod+f",
  MESSAGE_PREV: "alt+up",
  MESSAGE_NEXT: "alt+down",
  MESSAGE_JUMP: "mod+j",
  BLUR: "escape",
  SUBMIT_BLUR: "mod+enter",
  SWITCH_MESSAGING_MODE: "ctrl+s",
  RELOAD_WINDOW: "mod+shift+r",
  ZOOM_IN: "mod+=",
  ZOOM_OUT: "mod+-",
  RESET_ZOOM: "mod+0",
} as const;

export type ShortcutCategory = "general" | "navigation" | "panels" | "editor";

/**
 * Layouts a shortcut exists in. Several keys have different owners either side
 * of the channels layout flag, and a sheet that lists a key nothing handles is
 * worse than one that omits it.
 */
export type ShortcutAvailability = "channels-layout" | "no-channels-layout";

export interface KeyboardShortcut {
  id: string;
  keys: string;
  description: string;
  category: ShortcutCategory;
  context?: string;
  alternateKeys?: string;
  /** Absent means the shortcut works in every layout. */
  availability?: ShortcutAvailability;
}

export const KEYBOARD_SHORTCUTS: KeyboardShortcut[] = [
  {
    id: "new-task",
    keys: "mod+n",
    description: "New task",
    category: "general",
  },
  {
    id: "new-tab",
    keys: SHORTCUTS.NEW_TAB,
    description: "New tab",
    category: "navigation",
    context: "Channels",
    // The tab strip that owns this doesn't exist in the channels layout.
    availability: "no-channels-layout",
  },
  {
    id: "command-menu",
    keys: SHORTCUTS.COMMAND_MENU,
    description: "Open command menu",
    category: "general",
  },
  {
    id: "settings",
    keys: SHORTCUTS.SETTINGS,
    description: "Open settings",
    category: "general",
  },
  {
    id: "shortcuts",
    keys: SHORTCUTS.SHORTCUTS_SHEET,
    description: "Show keyboard shortcuts",
    category: "general",
  },
  {
    id: "zoom-in",
    keys: SHORTCUTS.ZOOM_IN,
    description: "Zoom in",
    category: "general",
  },
  {
    id: "zoom-out",
    keys: SHORTCUTS.ZOOM_OUT,
    description: "Zoom out",
    category: "general",
  },
  {
    id: "reset-zoom",
    keys: SHORTCUTS.RESET_ZOOM,
    description: "Reset zoom",
    category: "general",
  },
  {
    id: "switch-messaging-mode",
    keys: SHORTCUTS.SWITCH_MESSAGING_MODE,
    description: "Switch Steer / Queue mode",
    category: "editor",
    context: "Session composer",
  },
  {
    id: "inbox",
    keys: SHORTCUTS.INBOX,
    description: "Open Self-driving",
    category: "navigation",
  },
  {
    id: "switch-task",
    keys: "mod+1-9",
    description: "Switch to task 1-9",
    category: "navigation",
    // Yielded to switch-starred-channel under the channels layout.
    availability: "no-channels-layout",
  },
  {
    id: "switch-browser-tab",
    keys: "mod+1-9",
    description: "Switch to tab (9 = last tab)",
    category: "navigation",
    context: "Tabs",
    availability: "channels-layout",
  },
  {
    id: "focus-space-search",
    keys: SHORTCUTS.FOCUS_SPACE_SEARCH,
    description: "Search spaces",
    category: "navigation",
    context: "Spaces",
    availability: "channels-layout",
  },
  {
    id: "prev-task",
    keys: "mod+shift+[",
    description: "Previous task",
    category: "navigation",
    alternateKeys: "ctrl+shift+tab",
  },
  {
    id: "next-task",
    keys: "mod+shift+]",
    description: "Next task",
    category: "navigation",
    alternateKeys: "ctrl+tab",
  },
  {
    id: "archive-task",
    keys: SHORTCUTS.ARCHIVE_TASK,
    description: "Archive current task",
    category: "navigation",
    context: "Task detail",
  },
  {
    id: "space-up",
    keys: SHORTCUTS.SPACE_UP,
    description: "Previous space",
    category: "navigation",
  },
  {
    id: "space-down",
    keys: SHORTCUTS.SPACE_DOWN,
    description: "Next space",
    category: "navigation",
  },
  {
    id: "go-back",
    keys: SHORTCUTS.GO_BACK,
    description: "Go back",
    category: "navigation",
    alternateKeys: SHORTCUTS.GO_BACK_ALT,
  },
  {
    id: "go-forward",
    keys: SHORTCUTS.GO_FORWARD,
    description: "Go forward",
    category: "navigation",
    alternateKeys: SHORTCUTS.GO_FORWARD_ALT,
  },
  {
    id: "toggle-left-sidebar",
    keys: SHORTCUTS.TOGGLE_LEFT_SIDEBAR,
    description: "Toggle left sidebar",
    category: "navigation",
  },
  {
    id: "toggle-activity-panel",
    keys: SHORTCUTS.TOGGLE_ACTIVITY_PANEL,
    description: "Toggle activity panel",
    category: "panels",
    context: "Spaces",
    availability: "channels-layout",
  },
  {
    id: "toggle-review-panel",
    keys: SHORTCUTS.TOGGLE_REVIEW_PANEL,
    description: "Toggle diff view",
    category: "navigation",
  },
  {
    id: "switch-tab",
    keys: isMac ? "ctrl+1-9" : "alt+1-9",
    description: "Switch to tab 1-9",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "close-tab",
    keys: SHORTCUTS.CLOSE_TAB,
    description: "Close active tab",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "find-in-conversation",
    keys: SHORTCUTS.FIND_IN_CONVERSATION,
    description: "Find in conversation",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "message-prev",
    keys: SHORTCUTS.MESSAGE_PREV,
    description: "Previous message",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "message-next",
    keys: SHORTCUTS.MESSAGE_NEXT,
    description: "Next message",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "message-jump",
    keys: SHORTCUTS.MESSAGE_JUMP,
    description: "Jump to message",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "paste-as-file",
    keys: SHORTCUTS.PASTE_AS_FILE,
    description: "Paste as file attachment",
    category: "editor",
    context: "Message editor",
  },
  {
    id: "prompt-recall-prev",
    keys: "up",
    description: "Recall previous prompt",
    category: "editor",
    context: "Message editor",
  },
  {
    id: "prompt-recall-next",
    keys: "down",
    description: "Recall next prompt",
    category: "editor",
    context: "Message editor",
  },
  {
    id: "editor-bold",
    keys: "mod+b",
    description: "Bold",
    category: "editor",
    context: "Rich text editor",
  },
  {
    id: "editor-italic",
    keys: "mod+i",
    description: "Italic",
    category: "editor",
    context: "Rich text editor",
  },
  {
    id: "editor-underline",
    keys: "mod+u",
    description: "Underline",
    category: "editor",
    context: "Rich text editor",
  },
  {
    id: "editor-code",
    keys: "mod+e",
    description: "Inline code",
    category: "editor",
    context: "Rich text editor",
  },
];

export const CATEGORY_LABELS: Record<ShortcutCategory, string> = {
  general: "General",
  navigation: "Navigation",
  panels: "Panels & Tabs",
  editor: "Editor",
};

export function getShortcutsByCategory({
  channelsLayout = false,
  inboxEnabled = true,
}: {
  channelsLayout?: boolean;
  /** Off when channel reports replace the inbox and nothing handles its key. */
  inboxEnabled?: boolean;
} = {}): Record<ShortcutCategory, KeyboardShortcut[]> {
  const grouped: Record<ShortcutCategory, KeyboardShortcut[]> = {
    general: [],
    navigation: [],
    panels: [],
    editor: [],
  };
  const wanted: ShortcutAvailability = channelsLayout
    ? "channels-layout"
    : "no-channels-layout";
  for (const shortcut of KEYBOARD_SHORTCUTS) {
    if (shortcut.availability && shortcut.availability !== wanted) continue;
    if (!inboxEnabled && shortcut.id === "inbox") continue;
    grouped[shortcut.category].push(shortcut);
  }
  return grouped;
}

function formatKey(key: string): string {
  const k = key.trim().toLowerCase();
  if (k === "mod") return isMac ? "⌘" : "Ctrl";
  if (k === "shift") return isMac ? "⇧" : "Shift";
  if (k === "alt") return isMac ? "⌥" : "Alt";
  if (k === "ctrl") return isMac ? "⌃" : "Ctrl";
  if (k === "enter") return isMac ? "↩" : "Enter";
  if (k === "escape" || k === "esc") return "Esc";
  if (k === "up" || k === "arrowup") return "↑";
  if (k === "down" || k === "arrowdown") return "↓";
  if (k === "left" || k === "arrowleft") return "←";
  if (k === "right" || k === "arrowright") return "→";
  if (k === ",") return ",";
  if (k === "[") return "[";
  if (k === "]") return "]";
  if (k === "=") return "+";
  if (k === "-") return "-";
  if (k === "tab") return "Tab";
  if (k === "space") return "Space";
  return k.toUpperCase();
}

function extractHotkey(keys: string): string {
  if (keys.includes(",") && !keys.endsWith(",")) {
    return keys.split(",")[0];
  }
  return keys;
}

export function formatHotkey(keys: string): string {
  const hotkey = extractHotkey(keys);
  return hotkey
    .split("+")
    .map(formatKey)
    .join(isMac ? "" : "+");
}

export function formatHotkeyParts(keys: string): string[] {
  const hotkey = extractHotkey(keys);
  return hotkey.split("+").map(formatKey);
}
