import type { Click } from "./mouse";

export type GestureEnd =
  | { kind: "click"; at: Click }
  | { kind: "word"; at: Click }
  | { kind: "select"; from: Click; to: Click };

const DOUBLE_CLICK_MS = 400;

// The word under a column of a row's text, as a start and end (exclusive) column, or null on a space.
export function wordAt(
  text: string,
  column: number,
): { start: number; end: number } | null {
  if (column >= text.length || /\s/.test(text[column] ?? " ")) return null;
  let start = column;
  let end = column + 1;
  while (start > 0 && !/\s/.test(text[start - 1] ?? " ")) start--;
  while (end < text.length && !/\s/.test(text[end] ?? " ")) end++;
  return { start, end };
}

// Tells a click from a drag: a press and release on one cell clicks, a second click there straight after selects the
// word under it, and moving to any other cell selects.
export class Gesture {
  private start: Click | null = null;
  private dragged = false;
  private lastClick: { at: Click; time: number } | null = null;

  press(at: Click): void {
    this.start = at;
    this.dragged = false;
  }

  // The selection so far, or null when no press started one.
  drag(at: Click): { from: Click; to: Click } | null {
    if (!this.start) return null;
    if (at.column !== this.start.column || at.row !== this.start.row)
      this.dragged = true;
    return this.dragged ? { from: this.start, to: at } : null;
  }

  release(at: Click, now = Date.now()): GestureEnd | null {
    const start = this.start;
    if (!start) return null;
    this.drag(at);
    this.start = null;
    if (this.dragged) {
      this.lastClick = null;
      return { kind: "select", from: start, to: at };
    }
    const last = this.lastClick;
    this.lastClick = { at, time: now };
    const again =
      last !== null &&
      now - last.time <= DOUBLE_CLICK_MS &&
      last.at.column === at.column &&
      last.at.row === at.row;
    if (again) this.lastClick = null;
    return { kind: again ? "word" : "click", at };
  }
}
