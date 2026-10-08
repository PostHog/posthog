import type { ImageContent } from "@earendil-works/pi-ai";
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
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { inverseCells } from "./highlight";
import type { RunCommand } from "./models";
import type { Click } from "./mouse";
import { orange } from "./theme";

// Keys the app keeps for itself; everything else typed in a focused pane goes to its composer.
const APP_KEYS: KeyId[] = [
  "tab",
  "shift+tab",
  "ctrl+\\",
  "ctrl+shift+\\",
  "ctrl+|",
  "super+\\",
  "super+shift+\\",
  "super+|",
  "ctrl+c",
  "ctrl+d",
  "ctrl+n",
  "ctrl+b",
  "super+b",
  "ctrl+k",
  "super+k",
  "ctrl+;",
  "ctrl+q",
  "ctrl+r",
  "pageUp",
  "pageDown",
];

export function isAppKey(sequence: string): boolean {
  return APP_KEYS.some((key) => matchesKey(sequence, key));
}

export const PASTE_START = "\u001b[200~";
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
  { name: "effort", description: "Set how much this chat's model thinks" },
  {
    name: "compact",
    description: "Summarize older messages to free up context",
  },
  { name: "billing", description: "Choose who pays for new chats" },
  { name: "new", description: "Start a new chat" },
  { name: "rename", description: "Rename this chat" },
  { name: "rename-workspace", description: "Rename this workspace" },
  {
    name: "optimize",
    description: "Lay out this workspace's panes in an even grid",
  },
  {
    name: "expand",
    description: "Open this chat full width, as All tasks does",
  },
  { name: "search", description: "Search your tasks" },
  { name: "settings", description: "Open settings, like Ctrl+;" },
  { name: "clear", description: "Clear this local chat's conversation" },
  { name: "local", description: "Run new chats in this pane on this machine" },
  {
    name: "repo",
    description: "Pick the repositories new cloud chats in this pane clone",
  },
  { name: "cloud", description: "Run new chats in this pane in the cloud" },
  { name: "login", description: "Sign in to PostHog" },
  {
    name: "logout",
    description: "Sign out. Your workspaces stay for next time",
  },
];

// A point in the text: a logical line and a string index within it.
type Position = { line: number; col: number };

// pi's editor has no public way to place the cursor or to say how it wrapped the text, so these are its own fields for both.
// The composer tests cover each one, so a pi upgrade that renames them fails there first.
interface EditorInternals {
  state: { cursorLine: number };
  scrollOffset: number;
  lastWidth: number;
  buildVisualLineMap(
    width: number,
  ): { logicalLine: number; startCol: number; length: number }[];
  setCursorCol(col: number): void;
}

const graphemes = new Intl.Segmenter();
const before = (a: Position, b: Position): boolean =>
  a.line < b.line || (a.line === b.line && a.col < b.col);

// Faint grey, the same as the pane dividers, so the rule recedes behind the chat.
const RULE = (text: string): string => `\u001b[2;90m${text}\u001b[22;39m`;

// pi's editor, hosted in a pane: it asks this stub to repaint instead of owning the terminal.
export class Composer {
  private readonly editor: Editor;
  private shellMode = false;
  // Images waiting to be sent, by their marker; the numbers run on across messages.
  private readonly images = new Map<string, ImageContent>();
  private imageCount = 0;
  private suggestions: CombinedAutocompleteProvider | undefined;
  private selection: { from: Position; to: Position } | null = null;

  constructor(
    private readonly repaint: () => void,
    submit: (text: string, images: ImageContent[]) => void,
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
      const images = [...this.images]
        .filter(([marker]) => text.includes(marker))
        .map(([, image]) => image);
      this.images.clear();
      submit(message, images);
    };
  }

  // The run's own slash commands join the built-in ones; the built-ins win on a name clash.
  setCommands(commands: RunCommand[]): void {
    const builtIn = new Set(SLASH_COMMANDS.map((command) => command.name));
    this.suggestions = new CombinedAutocompleteProvider(
      [
        ...SLASH_COMMANDS,
        ...commands.filter((command) => !builtIn.has(command.name)),
      ],
      process.cwd(),
    );
    this.editor.setAutocompleteProvider(this.suggestions);
  }

  // An image shows as a marker in the text; deleting the marker before sending drops the image.
  attach(image: ImageContent): void {
    const marker = `[Image #${++this.imageCount}]`;
    this.images.set(marker, image);
    this.editor.insertTextAtCursor(marker);
    this.repaint();
  }

  // Puts back a message that could not be sent, with its images under the markers its text already carries.
  putBack(text: string, images: ImageContent[]): void {
    this.setText(text);
    const markers = text.match(/\[Image #\d+\]/g) ?? [];
    images.forEach((image, index) => {
      const marker = markers[index];
      if (marker) this.images.set(marker, image);
    });
  }

  showingSuggestions(): boolean {
    return this.editor.isShowingAutocomplete();
  }

  clear(): void {
    this.images.clear();
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
    // A selection is for copying; any key carries on from the cursor.
    this.selection = null;
    const empty = this.editor.getText() === "";
    const bang = sequence === "!" || decodeKittyPrintable(sequence) === "!";
    if (empty && !this.shellMode && bang) this.shellMode = true;
    else if (empty && this.shellMode && matchesKey(sequence, "backspace"))
      this.shellMode = false;
    else if (!this.deleteMarker(sequence)) this.editor.handleInput(sequence);
    this.repaint();
  }

  // pi's editor deletes one character per key, so Backspace or Delete beside an image marker removes the whole marker.
  // The image stays known, so a marker that undo puts back still sends it.
  private deleteMarker(sequence: string): boolean {
    const backward = matchesKey(sequence, "backspace");
    if (!backward && !matchesKey(sequence, "delete")) return false;
    const { line, col } = this.editor.getCursor();
    const text = this.editor.getLines()[line] ?? "";
    const marker = [...this.images.keys()].find((candidate) =>
      backward
        ? text.slice(0, col).endsWith(candidate)
        : text.startsWith(candidate, col),
    );
    if (!marker) return false;
    for (let step = 0; step < marker.length; step++)
      this.editor.handleInput(sequence);
    // Mid-delete the text can end in "#", which starts pi's file suggestions; setting the provider again cancels them.
    if (this.suggestions) this.editor.setAutocompleteProvider(this.suggestions);
    return true;
  }

  // Moves the cursor to the text under a cell of the drawn composer, where row 0 is its top rule.
  placeCursor(at: Click): void {
    const { line, col } = this.positionAt(at);
    this.internals().state.cursorLine = line;
    this.internals().setCursorCol(this.pastMarker(line, col));
    this.selection = null;
    this.repaint();
  }

  // Selects the text between two cells of the drawn composer, including the cell under each end.
  select(from: Click, to: Click): void {
    const forward = before(this.positionAt(from), this.positionAt(to));
    const [start, end] = forward ? [from, to] : [to, from];
    this.selection = {
      from: this.positionAt(start),
      to: this.positionAt({ ...end, column: end.column + 1 }),
    };
    this.repaint();
  }

  clearSelection(): void {
    if (!this.selection) return;
    this.selection = null;
    this.repaint();
  }

  // The selected text from the editor's own lines, so wrapping never adds a line break.
  selectedText(): string {
    if (!this.selection) return "";
    const { from, to } = this.selection;
    const lines = this.editor.getLines();
    if (from.line === to.line)
      return (lines[from.line] ?? "").slice(from.col, to.col);
    return [
      (lines[from.line] ?? "").slice(from.col),
      ...lines.slice(from.line + 1, to.line),
      (lines[to.line] ?? "").slice(0, to.col),
    ].join("\n");
  }

  // A click inside an image marker lands after it, where Backspace removes the whole marker.
  private pastMarker(line: number, col: number): number {
    const text = this.editor.getLines()[line] ?? "";
    for (const marker of this.images.keys()) {
      for (
        let start = text.indexOf(marker);
        start >= 0;
        start = text.indexOf(marker, start + 1)
      ) {
        if (col > start && col < start + marker.length)
          return start + marker.length;
      }
    }
    return col;
  }

  private internals(): EditorInternals {
    return this.editor as unknown as EditorInternals;
  }

  // The visual rows the editor drew last, top to bottom, scrolled as it scrolled them.
  private visibleRows(): {
    logicalLine: number;
    startCol: number;
    length: number;
  }[] {
    const { lastWidth, scrollOffset } = this.internals();
    return this.internals().buildVisualLineMap(lastWidth).slice(scrollOffset);
  }

  // The text position under a cell; rows above or below the input land on its first or last row.
  private positionAt({ row, column }: Click): Position {
    const rows = this.visibleRows();
    const visual = rows[Math.max(0, Math.min(row - 1, rows.length - 1))];
    if (!visual) return { line: 0, col: 0 };
    const line = this.editor.getLines()[visual.logicalLine] ?? "";
    const chunk = line.slice(visual.startCol, visual.startCol + visual.length);
    let cells = column - PROMPT_WIDTH;
    let offset = 0;
    for (const { segment } of graphemes.segment(chunk)) {
      const width = visibleWidth(segment);
      if (cells < width) break;
      cells -= width;
      offset += segment.length;
    }
    return { line: visual.logicalLine, col: visual.startCol + offset };
  }

  // Draws the selected part of an input row in inverse video.
  private highlight(row: string, index: number): string {
    if (!this.selection) return row;
    const { from, to } = this.selection;
    const visual = this.visibleRows()[index];
    if (!visual) return row;
    const rowStart = { line: visual.logicalLine, col: visual.startCol };
    const rowEnd = {
      line: visual.logicalLine,
      col: visual.startCol + visual.length,
    };
    const start = before(rowStart, from) ? from : rowStart;
    const end = before(to, rowEnd) ? to : rowEnd;
    if (start.line !== visual.logicalLine || !before(start, end)) return row;
    const line = this.editor.getLines()[visual.logicalLine] ?? "";
    const cellsTo = (col: number): number =>
      PROMPT_WIDTH + visibleWidth(line.slice(visual.startCol, col));
    return inverseCells(row, cellsTo(start.col), cellsTo(end.col));
  }

  // The input and its rule, and apart from them any suggestion list, which the pane floats over the chat.
  // A status, such as context and cost, ends the top rule on the right.
  render(
    width: number,
    focused: boolean,
    status = "",
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
      )
      .map((line, index) => this.highlight(line, index));
    const statusWidth = status ? visibleWidth(status) + 1 : 0;
    const top =
      status && statusWidth < width
        ? `${truncateToWidth(fullWidth(lines[0]), width - statusWidth, "")} ${status}`
        : fullWidth(lines[0]);
    const editor = [top, ...input];
    if (found <= 0) return { editor, popup: [] };
    // A plain closing rule goes: the pane edge already closes the input.
    if (!PLAIN_RULE.test(stripTerminalSequences(lines[found])))
      editor.push(fullWidth(lines[found]));
    return { editor, popup: lines.slice(found + 1) };
  }
}
