import { getSelectListTheme } from "@earendil-works/pi-coding-agent";
import {
  CombinedAutocompleteProvider,
  CURSOR_MARKER,
  decodeKittyPrintable,
  Editor,
  type KeyId,
  matchesKey,
  stripTerminalSequences,
  type TUI,
} from "@earendil-works/pi-tui";
import type { RunCommand } from "./models";

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
  "ctrl+q",
  "ctrl+r",
  "pageUp",
  "pageDown",
];

export function isAppKey(sequence: string): boolean {
  return APP_KEYS.some((key) => matchesKey(sequence, key));
}

const PASTE_START = "\u001b[200~";
const PLAIN_RULE = /^─+$/;
const INVERSE = "\u001b[7m";
// A grey block: lighter than the inverse cursor on light and dark themes alike.
const UNFOCUSED_CURSOR = "\u001b[100m";

// Text a person types or pastes, as opposed to navigation and control keys.
export function isTyping(sequence: string): boolean {
  if (sequence.startsWith(PASTE_START)) return true;
  if (decodeKittyPrintable(sequence) !== undefined) return true;
  return [...sequence].every((char) => char >= " " && char !== "\u007f");
}

// Commands the TUI handles itself; anything else starting with / goes to the agent.
export const SLASH_COMMANDS = [
  { name: "model", description: "Switch this chat's model" },
  { name: "new", description: "Start a new chat" },
  { name: "login", description: "Sign in to PostHog" },
  { name: "logout", description: "Sign out and clear your workspaces" },
];

// Faint grey, the same as the pane dividers, so the rule recedes behind the chat.
const RULE = (text: string): string => `\u001b[2;90m${text}\u001b[22;39m`;

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
      borderColor: RULE,
      selectList: getSelectListTheme(),
    });
    this.setCommands([]);
    this.editor.onSubmit = (text) => {
      if (!text.trim()) return;
      this.editor.addToHistory(text);
      submit(text);
    };
  }

  // The run's own slash commands join the built-in ones; the built-ins win on a name clash.
  setCommands(commands: RunCommand[]): void {
    const builtIn = new Set(SLASH_COMMANDS.map((command) => command.name));
    this.editor.setAutocompleteProvider(
      new CombinedAutocompleteProvider(
        [
          ...SLASH_COMMANDS,
          ...commands.filter((command) => !builtIn.has(command.name)),
        ],
        process.cwd(),
      ),
    );
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

  // The input and its rule, and apart from them any suggestion list, which the pane floats over the chat.
  render(
    width: number,
    focused: boolean,
  ): { editor: string[]; popup: string[] } {
    this.editor.focused = focused;
    // pi draws its cursor as an inverse block in every pane; only the focused one keeps it solid.
    const lines = this.editor
      .render(width)
      .map((line) => line.replace(CURSOR_MARKER, ""))
      .map((line) =>
        focused ? line : line.replaceAll(INVERSE, UNFOCUSED_CURSOR),
      );
    // pi closes the input with a rule (or a "↓ n more" line); suggestions follow it.
    const closing = lines.findLastIndex(
      (line, index) =>
        index > 0 && stripTerminalSequences(line).startsWith("─"),
    );
    if (closing <= 0) return { editor: lines, popup: [] };
    // A plain closing rule goes: the pane edge already closes the input.
    const keep = PLAIN_RULE.test(stripTerminalSequences(lines[closing]))
      ? closing
      : closing + 1;
    return { editor: lines.slice(0, keep), popup: lines.slice(closing + 1) };
  }
}
