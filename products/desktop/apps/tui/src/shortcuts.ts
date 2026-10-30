import type { Key } from "ink";

export type Shortcut =
  | "splitRight"
  | "splitDown"
  | "close"
  | "newChat"
  | "quit"
  | "reload";

export function shortcutFor(input: string, key: Key): Shortcut | null {
  const letter = input.toLowerCase();
  if ((key.ctrl || key.super) && letter === "s") {
    return key.shift ? "splitDown" : "splitRight";
  }
  // Legacy terminals send Ctrl+Shift+S as Ctrl+S, so Ctrl+\ (a raw byte there) also splits down.
  if (input === "\x1c" || (key.ctrl && input === "\\")) return "splitDown";
  if (key.ctrl && (letter === "c" || letter === "d")) return "close";
  if (key.ctrl && letter === "n") return "newChat";
  if (key.ctrl && letter === "q") return "quit";
  if (key.ctrl && letter === "r") return "reload";
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
