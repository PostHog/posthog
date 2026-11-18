/**
 * In-memory list backing the demo's focusable footer.
 *
 * `FooterInbox` owns just enough state for the POC: an ordered list of
 * items, which one (if any) is currently "focused" by the keyboard, and a
 * single change listener the footer component uses to re-render itself.
 * It has no pi/TUI imports so it's trivial to unit test in isolation.
 */

export interface FooterItem {
  id: string;
  label: string;
  detail: string;
  createdAt: number;
}

export class FooterInbox {
  private items: FooterItem[] = [];
  private focusedIndex: number | null = null;
  private onChange?: () => void;

  /** Register the sole change listener (the active footer component). */
  setOnChange(listener: () => void): () => void {
    this.onChange = listener;
    return () => {
      if (this.onChange === listener) this.onChange = undefined;
    };
  }

  private notify(): void {
    this.onChange?.();
  }

  add(item: FooterItem): void {
    this.items.push(item);
    this.notify();
  }

  clear(): void {
    this.items = [];
    this.focusedIndex = null;
    this.notify();
  }

  getItems(): readonly FooterItem[] {
    return this.items;
  }

  hasItems(): boolean {
    return this.items.length > 0;
  }

  isFocused(): boolean {
    return this.focusedIndex !== null;
  }

  getFocusedIndex(): number | null {
    return this.focusedIndex;
  }

  getFocusedItem(): FooterItem | undefined {
    return this.focusedIndex === null
      ? undefined
      : this.items[this.focusedIndex];
  }

  /**
   * Called when the editor sees Down with nothing left to do locally.
   * Moves keyboard focus into the footer's first item, if any exists.
   * Returns whether focus actually moved.
   */
  focusFromEditor(): boolean {
    if (this.items.length === 0) return false;
    this.focusedIndex = 0;
    this.notify();
    return true;
  }

  moveDown(): void {
    if (this.focusedIndex === null || this.items.length === 0) return;
    this.focusedIndex = Math.min(this.focusedIndex + 1, this.items.length - 1);
    this.notify();
  }

  /** Moves up within the footer, or hands focus back to the editor from the top item. */
  moveUp(): void {
    if (this.focusedIndex === null) return;
    if (this.focusedIndex === 0) {
      this.blur();
      return;
    }
    this.focusedIndex -= 1;
    this.notify();
  }

  blur(): void {
    if (this.focusedIndex === null) return;
    this.focusedIndex = null;
    this.notify();
  }
}
