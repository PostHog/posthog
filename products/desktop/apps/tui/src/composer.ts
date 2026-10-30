import { getSelectListTheme } from "@earendil-works/pi-coding-agent";
import {
  CURSOR_MARKER,
  Editor,
  type KeyId,
  matchesKey,
  type TUI,
} from "@earendil-works/pi-tui";

// Keys the app keeps for itself; everything else typed in a focused pane goes to its composer.
const APP_KEYS: KeyId[] = [
  "tab",
  "shift+tab",
  "ctrl+s",
  "ctrl+shift+s",
  "super+s",
  "super+shift+s",
  "ctrl+\\",
  "ctrl+c",
  "ctrl+d",
  "pageUp",
  "pageDown",
];

export function isAppKey(sequence: string): boolean {
  return APP_KEYS.some((key) => matchesKey(sequence, key));
}

const DIM = (text: string): string => `\u001b[2m${text}\u001b[22m`;

// pi's editor, hosted in a pane: it asks this stub to repaint instead of owning the terminal.
export class Composer {
  private readonly editor: Editor;

  constructor(private readonly repaint: () => void) {
    const host = {
      requestRender: repaint,
      terminal: { rows: 40 },
    } as unknown as TUI;
    this.editor = new Editor(host, {
      borderColor: DIM,
      selectList: getSelectListTheme(),
    });
    this.editor.disableSubmit = true;
  }

  handleInput(sequence: string): void {
    this.editor.handleInput(sequence);
    this.repaint();
  }

  render(width: number, focused: boolean): string[] {
    this.editor.focused = focused;
    return this.editor
      .render(width)
      .map((line) => line.replace(CURSOR_MARKER, ""));
  }
}
