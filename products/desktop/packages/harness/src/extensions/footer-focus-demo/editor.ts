/**
 * A thin `CustomEditor` wrapper (tui.md "Pattern 7: Custom Editor") that
 * hands keyboard focus to the footer on Down, and back to the editor on
 * Up/Escape from the footer's first item.
 *
 * The footer itself is never part of pi-tui's real focus chain (only
 * overlays and `Focusable` components are) — so "focus" here is a small
 * bit of state on `FooterInbox`, and this editor is what actually decides,
 * on every keystroke, whether the editor or the footer owns arrow/enter.
 */

import {
  CustomEditor,
  type KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import {
  type EditorTheme,
  Key,
  matchesKey,
  type TUI,
} from "@earendil-works/pi-tui";
import type { FooterInbox } from "./inbox";

export class FooterAwareEditor extends CustomEditor {
  constructor(
    tui: TUI,
    theme: EditorTheme,
    keybindings: KeybindingsManager,
    private readonly inbox: FooterInbox,
    private readonly onOpenFocusedItem: () => void,
  ) {
    super(tui, theme, keybindings);
  }

  override handleInput(data: string): void {
    if (this.inbox.isFocused()) {
      this.handleFooterFocusedInput(data);
      return;
    }

    // Only steal Down when the editor has nothing else to do with it
    // (empty input, cursor already at the only/last line) so normal
    // multi-line editing and history navigation keep working.
    if (
      matchesKey(data, Key.down) &&
      this.getText() === "" &&
      this.inbox.hasItems()
    ) {
      if (this.inbox.focusFromEditor()) {
        this.tui.requestRender();
        return;
      }
    }

    super.handleInput(data);
  }

  private handleFooterFocusedInput(data: string): void {
    if (matchesKey(data, Key.down)) {
      this.inbox.moveDown();
      this.tui.requestRender();
      return;
    }
    if (matchesKey(data, Key.up)) {
      this.inbox.moveUp();
      this.tui.requestRender();
      return;
    }
    if (matchesKey(data, Key.enter)) {
      this.onOpenFocusedItem();
      return;
    }
    if (matchesKey(data, Key.escape)) {
      this.inbox.blur();
      this.tui.requestRender();
      return;
    }
    // Let ctrl+c / ctrl+d keep working as global escape hatches even while
    // the footer has focus; swallow everything else (typing shouldn't leak
    // into the editor while the footer is focused).
    if (matchesKey(data, Key.ctrl("c")) || matchesKey(data, Key.ctrl("d"))) {
      super.handleInput(data);
    }
  }
}
