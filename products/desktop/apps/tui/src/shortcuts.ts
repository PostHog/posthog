import type { Key } from "ink";

export type Shortcut =
  | "splitRight"
  | "splitDown"
  | "close"
  | "newChat"
  | "newChatOutside"
  | "search"
  | "searchFullScreen"
  | "settings"
  | "quit"
  | "reload"
  | "toggleSidebar"
  | "cycleMode"
  | "cycleModeBack"
  | "historyBack"
  | "historyForward"
  | "togglePin";

export function shortcutFor(input: string, key: Key): Shortcut | null {
  const letter = input.toLowerCase();
  // Ctrl+\ splits side by side, as in VS Code, and Ctrl+Shift+\ (Ctrl+|) stacks.
  // Legacy terminals send both as one raw byte, so Option (sent as Meta) is the way to stack there.
  const modified = key.ctrl || key.super || key.meta;
  if (modified && (input === "|" || (input === "\\" && key.shift)))
    return "splitDown";
  if (input === "\x1c" || (modified && input === "\\")) return "splitRight";
  if (key.ctrl && (letter === "c" || letter === "d")) return "close";
  // Shift needs the kitty keyboard protocol: a legacy terminal sends Ctrl+Shift+N as Ctrl+N.
  if (key.ctrl && key.shift && letter === "n") return "newChatOutside";
  if (key.ctrl && letter === "n") return "newChat";
  // Most macOS terminals keep Cmd+K for clearing the screen, so Ctrl+K searches too.
  if ((key.ctrl || key.super) && key.shift && letter === "k")
    return "searchFullScreen";
  if ((key.ctrl || key.super) && letter === "k") return "search";
  if (key.ctrl && input === ";") return "settings";
  if (key.ctrl && letter === "q") return "quit";
  // As in VS Code. Inside tmux, Ctrl+B is tmux's own prefix, so Cmd+B does it too.
  if ((key.ctrl || key.super) && letter === "b") return "toggleSidebar";
  if (key.ctrl && letter === "r") return "reload";
  if (key.ctrl && letter === "p") return "togglePin";
  // Ctrl+M needs the kitty keyboard protocol, since a legacy terminal sends it as Enter.
  if (key.ctrl && letter === "m")
    return key.shift ? "cycleModeBack" : "cycleMode";
  // Ctrl+[ and Ctrl+] step back and forward through the chats visited. A legacy terminal sends Ctrl+[ as Esc,
  // so there only Ctrl+] (one raw byte) works.
  if (key.ctrl && input === "[") return "historyBack";
  if (input === "\x1d" || (key.ctrl && input === "]")) return "historyForward";
  return null;
}

// Ink drops Option (Meta) from \ and |, so a legacy terminal's Option splits are read from the raw sequence.
export function optionSplitFor(sequence: string): "row" | "column" | null {
  if (sequence === "\x1b\\") return "row";
  if (sequence === "\x1b|") return "column";
  return null;
}

// The first press arms; a second press inside the window confirms, like Claude Code's double Ctrl+C.
export class DoublePress {
  private armedAt: number | null = null;

  constructor(private readonly windowMs: number) {}

  press(now: number): boolean {
    if (this.armedAt !== null && now - this.armedAt <= this.windowMs) {
      this.armedAt = null;
      return true;
    }
    this.armedAt = now;
    return false;
  }
}
