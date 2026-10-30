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
  visibleWidth,
} from "@earendil-works/pi-tui";
import type { RunCommand } from "./models";
import { orange } from "./theme";

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
// The prompt before the input, "❯ " or "! ", in cells.
const PROMPT_WIDTH = 2;

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
  { name: "local", description: "Run new chats in this pane on this machine" },
  { name: "cloud", description: "Run new chats in this pane in the cloud" },
  { name: "login", description: "Sign in to PostHog" },
  { name: "logout", description: "Sign out and clear your workspaces" },
];

// Faint grey, the same as the pane dividers, so the rule recedes behind the chat.
const RULE = (text: string): string => `\u001b[2;90m${text}\u001b[22;39m`;

// pi's editor, hosted in a pane: it asks this stub to repaint instead of owning the terminal.
export class Composer {
  private readonly editor: Editor;
  private shellMode = false;

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
      const message = this.shellMode ? `!${text}` : text;
      this.editor.addToHistory(message);
      // Off before submit, since the app can put a command it could not run back with setText.
      this.shellMode = false;
      submit(message);
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

  showingSuggestions(): boolean {
    return this.editor.isShowingAutocomplete();
  }

  clear(): void {
    this.setText("");
  }

  isEmpty(): boolean {
    return this.editor.getText().trim() === "";
  }

  // In shell mode the text is a command to run, not a message for the agent.
  isShellCommand(): boolean {
    return this.shellMode;
  }

  // Text with a leading ! comes back as a command in shell mode.
  setText(text: string): void {
    this.shellMode = text.startsWith("!");
    this.editor.setText(this.shellMode ? text.slice(1) : text);
    this.repaint();
  }

  // ! in an empty composer enters shell mode instead of typing; Backspace on an empty command leaves it.
  handleInput(sequence: string): void {
    const empty = this.editor.getText() === "";
    const bang = sequence === "!" || decodeKittyPrintable(sequence) === "!";
    if (empty && !this.shellMode && bang) this.shellMode = true;
    else if (empty && this.shellMode && matchesKey(sequence, "backspace"))
      this.shellMode = false;
    else this.editor.handleInput(sequence);
    this.repaint();
  }

  // The input and its rule, and apart from them any suggestion list, which the pane floats over the chat.
  render(
    width: number,
    focused: boolean,
  ): { editor: string[]; popup: string[] } {
    this.editor.focused = focused;
    // Shell mode turns the rule and the prompt PostHog orange, so it is hard to miss.
    this.editor.borderColor = this.shellMode ? orange : RULE;
    const prompt = this.shellMode ? orange("!") : "❯";
    // pi draws its cursor as an inverse block in every pane; only the focused pane shows one.
    const lines = this.editor
      .render(Math.max(1, width - PROMPT_WIDTH))
      .map((line) => line.replace(CURSOR_MARKER, ""))
      .map((line) => (focused ? line : line.replaceAll(INVERSE, "")));
    // pi closes the input with a rule (or a "↓ n more" line); suggestions follow it.
    const found = lines.findLastIndex(
      (line, index) =>
        index > 0 && stripTerminalSequences(line).startsWith("─"),
    );
    const closing = found > 0 ? found : lines.length;
    // The prompt sits before the first input row, wrapped rows line up under the text, and the rules run full width.
    const fullWidth = (line: string): string =>
      `${line}${this.editor.borderColor("─".repeat(Math.max(0, width - visibleWidth(line))))}`;
    const input = lines
      .slice(1, closing)
      .map((line, index) =>
        index === 0
          ? `${prompt} ${line}`
          : `${" ".repeat(PROMPT_WIDTH)}${line}`,
      );
    const editor = [fullWidth(lines[0]), ...input];
    if (found <= 0) return { editor, popup: [] };
    // A plain closing rule goes: the pane edge already closes the input.
    if (!PLAIN_RULE.test(stripTerminalSequences(lines[found])))
      editor.push(fullWidth(lines[found]));
    return { editor, popup: lines.slice(found + 1) };
  }
}
