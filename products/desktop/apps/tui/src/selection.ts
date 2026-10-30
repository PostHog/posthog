import type { Click } from "./mouse";

export type GestureEnd =
  | { kind: "click"; at: Click }
  | { kind: "select"; from: Click; to: Click };

// Tells a click from a drag: a press and release on one cell clicks, and moving to any other cell selects.
export class Gesture {
  private start: Click | null = null;
  private dragged = false;

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

  release(at: Click): GestureEnd | null {
    const start = this.start;
    if (!start) return null;
    this.drag(at);
    this.start = null;
    return this.dragged
      ? { kind: "select", from: start, to: at }
      : { kind: "click", at };
  }
}
