import { getSelectListTheme } from "@earendil-works/pi-coding-agent";
import {
  CURSOR_MARKER,
  decodeKittyPrintable,
  Editor,
  type KeyId,
  matchesKey,
  stripTerminalSequences,
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
  "ctrl+n",
  "pageUp",
  "pageDown",
];

export function isAppKey(sequence: string): boolean {
  return APP_KEYS.some((key) => matchesKey(sequence, key));
}

const PASTE_START = "\u001b[200~";
const PLAIN_RULE = /^─+$/;

// Text a person types or pastes, as opposed to navigation and control keys.
export function isTyping(sequence: string): boolean {
  if (sequence.startsWith(PASTE_START)) return true;
  if (decodeKittyPrintable(sequence) !== undefined) return true;
  return [...sequence].every((char) => char >= " " && char !== "\u007f");
}

const DIM = (text: string): string => `\u001b[2m${text}\u001b[22m`;

// pi's editor, hosted in a pane: it asks this stub to repaint instead of owning the terminal.
export class Composer {
  private readonly editor: Editor;

  constructor(
    private readonly repaint: () => void,
    submit: (text: string) => void,
  ) {
    const host = {
      requestRender: repaint,
      terminal: { rows: 40 },
    } as unknown as TUI;
    this.editor = new Editor(host, {
      borderColor: DIM,
      selectList: getSelectListTheme(),
    });
    this.editor.onSubmit = (text) => {
      if (!text.trim()) return;
      this.editor.addToHistory(text);
      submit(text);
    };
  }

  isEmpty(): boolean {
    return this.editor.getText().trim() === "";
  }

  setText(text: string): void {
    this.editor.setText(text);
    this.repaint();
  }

  handleInput(sequence: string): void {
    this.editor.handleInput(sequence);
    this.repaint();
  }

  render(width: number, focused: boolean): string[] {
    this.editor.focused = focused;
    const lines = this.editor
      .render(width)
      .map((line) => line.replace(CURSOR_MARKER, ""));
    // pi closes the input with a second rule; the pane edge already does that job.
    const bottomRule = lines.findLastIndex(
      (line, index) =>
        index > 0 && PLAIN_RULE.test(stripTerminalSequences(line)),
    );
    return bottomRule > 0 ? lines.toSpliced(bottomRule, 1) : lines;
  }
}
