import { isMac } from "@posthog/ui/utils/platform";

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
  TOGGLE_REVIEW_PANEL: "mod+shift+b",
  PREV_TASK: "mod+shift+[,ctrl+shift+tab",
  NEXT_TASK: "mod+shift+],ctrl+tab",
  CLOSE_TAB: "mod+w",
  SWITCH_TAB: "ctrl+1,ctrl+2,ctrl+3,ctrl+4,ctrl+5,ctrl+6,ctrl+7,ctrl+8,ctrl+9",
  SWITCH_TASK: "mod+1,mod+2,mod+3,mod+4,mod+5,mod+6,mod+7,mod+8,mod+9",
  OPEN_IN_EDITOR: "mod+o",
  COPY_PATH: "mod+shift+c",
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

export interface KeyboardShortcut {
  id: string;
  keys: string;
  description: string;
  category: ShortcutCategory;
  context?: string;
  alternateKeys?: string;
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
    description: "Open inbox",
    category: "navigation",
  },
  {
    id: "switch-task",
    keys: "mod+1-9",
    description: "Switch to task 1-9",
    category: "navigation",
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
    id: "toggle-review-panel",
    keys: SHORTCUTS.TOGGLE_REVIEW_PANEL,
    description: "Toggle review panel",
    category: "navigation",
  },
  {
    id: "switch-tab",
    keys: "ctrl+1-9",
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
    id: "open-in-editor",
    keys: SHORTCUTS.OPEN_IN_EDITOR,
    description: "Open in external editor",
    category: "panels",
    context: "Task detail",
  },
  {
    id: "copy-path",
    keys: SHORTCUTS.COPY_PATH,
    description: "Copy file path",
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

export function getShortcutsByCategory(): Record<
  ShortcutCategory,
  KeyboardShortcut[]
> {
  const grouped: Record<ShortcutCategory, KeyboardShortcut[]> = {
    general: [],
    navigation: [],
    panels: [],
    editor: [],
  };
  for (const shortcut of KEYBOARD_SHORTCUTS) {
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
