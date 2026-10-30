import type { AssistantMessage } from "@earendil-works/pi-ai";
import {
  AssistantMessageComponent,
  getMarkdownTheme,
  UserMessageComponent,
} from "@earendil-works/pi-coding-agent";
import {
  type Component,
  Container,
  ScrollView,
  Spacer,
  sliceByColumn,
  stripTerminalSequences,
  Text,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";
import { linkAt } from "./links";
import type { Click } from "./mouse";
import { orange } from "./theme";
import {
  type ShellLine,
  type ToolLine,
  type TranscriptLine,
  toolSummary,
} from "./transcript";

// Shell-integration prompt marks (OSC 133) that pi emits for its own screen.
const PROMPT_MARKS = new RegExp(`${"\u001b"}\\]133;[A-Z]${"\u0007"}`, "g");
const DIM = (text: string): string => `\u001b[2m${text}\u001b[22m`;
const TOOL_MARKS: Record<string, string> = {
  completed: "\u001b[32m●\u001b[39m",
  failed: "\u001b[31m●\u001b[39m",
  in_progress: "\u001b[33m●\u001b[39m",
};
const RED = (text: string): string => `\u001b[31m${text}\u001b[39m`;
// Commands the user ran share the composer's shell-mode colour.
const SHELL_COLOUR = orange;
const OLDER_ROW = "older";
// Output lines an expanded tool call shows before it cuts off.
const OUTPUT_LINES = 5;
const BOLD = (text: string): string => `\u001b[1m${text}\u001b[22m`;
// Cells the highlight covers, and the cells it travels past the text before it comes round again.
const SHIMMER_WIDTH = 3;
const SHIMMER_PAUSE = 8;

// A highlight that sweeps along the text, advancing with the clock on each repaint.
export function shimmer(text: string, now = Date.now()): string {
  const chars = [...text];
  const head = Math.floor(now / 80) % (chars.length + SHIMMER_PAUSE);
  return chars
    .map((char, index) =>
      index <= head && index > head - SHIMMER_WIDTH ? BOLD(char) : char,
    )
    .join("");
}

export interface ChatNotice {
  text: string;
  // Said in lighter text after it, such as the command a call runs and how long the turn has taken.
  detail?: string;
  tone: "working" | "error" | "done";
}

// The run's status line; a working one shimmers.
class NoticeRow implements Component {
  constructor(private readonly notice: ChatNotice) {}

  render(): string[] {
    if (this.notice.tone === "error") {
      return [` \u001b[31m${this.notice.text}\u001b[39m`];
    }
    if (this.notice.tone === "done") return [DIM(` ✻ ${this.notice.text}`)];
    const detail = this.notice.detail ? ` ${this.notice.detail}` : "";
    return [`${DIM(" ✻")} ${shimmer(this.notice.text)}${DIM(detail)}`];
  }

  invalidate(): void {}
}

function assistantMessage(text: string): AssistantMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    stopReason: "stop",
    timestamp: 0,
  } as AssistantMessage;
}

const isBlank = (line: string): boolean =>
  stripTerminalSequences(line).trim() === "";

// A cell of the whole transcript: the row counts from its first line, not from the top of the screen.
interface Cell {
  row: number;
  column: number;
}

const before = (a: Cell, b: Cell): boolean =>
  a.row < b.row || (a.row === b.row && a.column < b.column);

// The text a line draws from column start up to column end, without styles or its trailing padding.
function textBetween(line: string, start: number, end: number): string {
  const width = Math.min(
    end,
    visibleWidth(stripTerminalSequences(line).trimEnd()),
  );
  if (width <= start) return "";
  return stripTerminalSequences(sliceByColumn(line, start, width - start));
}

// pi pads its message blocks for a full screen; panes keep them tight and space them here instead.
class Trimmed implements Component {
  constructor(private readonly inner: Component) {}

  render(width: number): string[] {
    const lines = this.inner.render(width);
    let start = 0;
    let end = lines.length;
    while (start < end && isBlank(lines[start])) start++;
    while (end > start && isBlank(lines[end - 1])) end--;
    return lines.slice(start, end);
  }

  invalidate(): void {
    this.inner.invalidate();
  }
}

type Block = TranscriptLine | { kind: "tools"; id: string; tools: ToolLine[] };

// Consecutive tool calls read as one row, which a click opens.
function blocksOf(lines: TranscriptLine[]): Block[] {
  const blocks: Block[] = [];
  for (const line of lines) {
    const last = blocks.at(-1);
    if (line.kind === "tool" && last?.kind === "tools") last.tools.push(line);
    else if (line.kind === "tool")
      blocks.push({ kind: "tools", id: line.id, tools: [line] });
    else blocks.push(line);
  }
  return blocks;
}

class ToolGroup implements Component {
  constructor(
    private readonly tools: ToolLine[],
    private readonly isOpen: () => boolean,
    private readonly isHovered: () => boolean,
    // While the turn is open, the group's row is the run's status line.
    private readonly live: ChatNotice | null = null,
  ) {}

  render(width: number): string[] {
    const open = this.isOpen();
    const failed = this.tools.filter((tool) => tool.status === "failed").length;
    const arrow = open ? "▾" : "▸";
    // Under the pointer it goes from grey to full colour, so it reads as clickable.
    const dim = this.isHovered() ? (text: string): string => text : DIM;
    const label = this.live
      ? `${dim(arrow)} ${shimmer(this.live.text)}${dim(this.live.detail ? ` ${this.live.detail}` : "")}`
      : dim(`${arrow} ${toolSummary(this.tools)}`);
    const summary = `${label}${failed ? ` ${DIM("·")} ${RED(`${failed} failed`)}` : ""}`;
    const lines = [truncateToWidth(` ${summary}`, width)];
    if (!open) return lines;
    for (const tool of this.tools) {
      const mark = TOOL_MARKS[tool.status] ?? DIM("●");
      lines.push(
        truncateToWidth(`   ${mark} ${tool.title} ${DIM(tool.detail)}`, width),
      );
      const output = tool.output.split("\n").filter((line) => line.trim());
      output.slice(0, OUTPUT_LINES).forEach((line, index) => {
        const prefix = index === 0 ? "⎿" : " ";
        lines.push(truncateToWidth(DIM(`     ${prefix} ${line}`), width));
      });
      if (output.length > OUTPUT_LINES)
        lines.push(DIM(`       … +${output.length - OUTPUT_LINES} lines`));
    }
    return lines;
  }

  invalidate(): void {}
}

// A command the user ran: the command in the shell colour, then the start of its output.
class ShellBlock implements Component {
  constructor(private readonly line: ShellLine) {}

  render(width: number): string[] {
    const mark = this.line.status === "failed" ? RED("!") : SHELL_COLOUR("!");
    const lines = [
      truncateToWidth(` ${mark} ${SHELL_COLOUR(this.line.command)}`, width),
    ];
    if (this.line.status === "in_progress" || this.line.status === "pending")
      lines.push(DIM("   ⎿ Running…"));
    const output = this.line.output.split("\n").filter((line) => line.trim());
    output.slice(0, OUTPUT_LINES).forEach((line, index) => {
      const prefix = index === 0 ? "⎿" : " ";
      lines.push(truncateToWidth(DIM(`   ${prefix} ${line}`), width));
    });
    if (output.length > OUTPUT_LINES)
      lines.push(DIM(`     … +${output.length - OUTPUT_LINES} lines`));
    return lines;
  }

  invalidate(): void {}
}

// Each change between user, tool and agent blocks gets one blank line.
const needsGap = (previous: Block | undefined, line: Block): boolean =>
  previous !== undefined && previous.kind !== line.kind;

function componentFor(line: TranscriptLine): Component {
  const markdown = getMarkdownTheme();
  switch (line.kind) {
    case "user":
      return new UserMessageComponent(line.text, markdown);
    case "assistant":
      return new AssistantMessageComponent(
        assistantMessage(line.text),
        false,
        markdown,
      );
    case "notice":
      return new Text(DIM(line.text), 1, 0);
    case "shell":
      return new ShellBlock(line);
    // Tool calls render as groups; offered actions show in the picker.
    case "tool":
    case "actions":
      return new Text("", 0, 0);
  }
}

// One pane's chat: pi's message components inside pi's ScrollView, clipped to the pane by us.
export class ChatView {
  private items: { id: string; component: Component }[] = [];
  private readonly scroll = new ScrollView(new Container(), { follow: "end" });
  // The message at the top of the screen, so new history above it does not move the reader.
  private anchor: { id: string; within: number } | null = null;
  private transcriptChanged = false;
  // Tool groups the reader opened, and where each item sat in the last render, for clicks.
  private readonly expanded = new Set<string>();
  private groups = new Set<string>();
  private hovered: string | null = null;
  private rows: { id: string; start: number; end: number }[] = [];
  // The lines on screen after the last render, for finding the link under a click.
  private shown: string[] = [];
  // Every transcript line and the chat's size at the last render, for selections.
  private content: string[] = [];
  private size = { width: 0, height: 0 };
  private selection: { anchor: Cell; head: Cell } | null = null;

  setTranscript(
    lines: TranscriptLine[],
    {
      hasOlder = false,
      notice = null,
    }: { hasOlder?: boolean; notice?: ChatNotice | null } = {},
  ): void {
    // Offered actions show in the pane's picker, not in the scrollback.
    const shown = blocksOf(lines.filter((line) => line.kind !== "actions"));
    this.groups = new Set(
      shown.flatMap((block) => (block.kind === "tools" ? [block.id] : [])),
    );
    // An open turn's latest tool calls and its status read as one row, not two that say the same.
    const folded =
      notice?.tone === "working" && shown.at(-1)?.kind === "tools"
        ? notice
        : null;
    this.items = shown.flatMap((block, index) => {
      const component =
        block.kind === "tools"
          ? new ToolGroup(
              block.tools,
              () => this.expanded.has(block.id),
              () => this.hovered === block.id,
              index === shown.length - 1 ? folded : null,
            )
          : new Trimmed(componentFor(block));
      const item = { id: block.id, component };
      return needsGap(shown[index - 1], block)
        ? [{ id: `${block.id}:gap`, component: new Spacer(1) }, item]
        : [item];
    });
    if (notice && !folded) {
      this.items.push(
        { id: "notice:gap", component: new Spacer(1) },
        { id: "notice", component: new NoticeRow(notice) },
      );
    }
    if (hasOlder) {
      this.items.unshift({
        id: OLDER_ROW,
        component: new Text(DIM("Loading earlier messages…"), 1, 0),
      });
    }
    this.transcriptChanged = true;
  }

  render(width: number, height: number): string[] {
    const contentWidth = this.scroll.getContentWidth(width);
    const starts = new Map<string, number>();
    const content: string[] = [];
    this.rows = [];
    for (const { id, component } of this.items) {
      starts.set(id, content.length);
      content.push(...component.render(contentWidth));
      this.rows.push({ id, start: starts.get(id) ?? 0, end: content.length });
    }
    this.content = content.map((line) => line.replace(PROMPT_MARKS, ""));
    this.size = { width: contentWidth, height };
    this.scroll.updateLayout(content.length, height, () => {});
    const start = this.anchor ? starts.get(this.anchor.id) : undefined;
    if (
      this.transcriptChanged &&
      this.anchor &&
      start !== undefined &&
      !this.scroll.isFollowingEnd
    ) {
      this.scroll.scrollTo(start + this.anchor.within);
    }
    this.transcriptChanged = false;

    const top = this.scroll.scrollTop;
    const anchorItem = [...starts].filter(([, at]) => at <= top).at(-1);
    this.anchor = anchorItem
      ? { id: anchorItem[0], within: top - anchorItem[1] }
      : null;
    const visible = this.content
      .slice(top, top + height)
      .map((line, index) => this.highlight(line, top + index))
      // Ink gives an empty string no height, so blank lines carry a space.
      .map((line) => line || " ");
    this.shown = visible;
    return [...visible, ...Array<string>(height - visible.length).fill(" ")];
  }

  private groupAt(row: number | null): string | null {
    if (row === null) return null;
    const at = this.scroll.scrollTop + row;
    const hit = this.rows.find(({ start, end }) => at >= start && at < end);
    return hit && this.groups.has(hit.id) ? hit.id : null;
  }

  // Selects from one cell of the chat on screen to another; cells past the chat's edges count as its edges.
  select(from: Click, to: Click): void {
    this.selection = { anchor: this.cellAt(from), head: this.cellAt(to) };
  }

  clearSelection(): void {
    this.selection = null;
  }

  // The selected text as drawn, one line per row.
  selectedText(): string {
    const range = this.range();
    if (!range) return "";
    const rows: string[] = [];
    for (let row = range.start.row; row <= range.end.row; row++) {
      const [start, end] = this.columnsOn(row, range);
      rows.push(textBetween(this.content[row] ?? "", start, end));
    }
    return rows.join("\n");
  }

  private cellAt({ row, column }: Click): Cell {
    const clamp = (value: number, size: number): number =>
      Math.max(0, Math.min(value, size - 1));
    return {
      row: this.scroll.scrollTop + clamp(row, this.size.height),
      column: clamp(column, this.size.width),
    };
  }

  private range(): { start: Cell; end: Cell } | null {
    if (!this.selection) return null;
    const { anchor, head } = this.selection;
    return before(head, anchor)
      ? { start: head, end: anchor }
      : { start: anchor, end: head };
  }

  // The selected columns of a transcript row, end exclusive.
  private columnsOn(
    row: number,
    range: { start: Cell; end: Cell },
  ): [number, number] {
    if (row < range.start.row || row > range.end.row) return [0, 0];
    return [
      row === range.start.row ? range.start.column : 0,
      row === range.end.row ? range.end.column + 1 : Number.POSITIVE_INFINITY,
    ];
  }

  // Draws a row's selected text in inverse video, without its own styles, so it reads as one block.
  private highlight(line: string, row: number): string {
    const range = this.range();
    if (!range) return line;
    const [start, end] = this.columnsOn(row, range);
    const text = textBetween(line, start, end);
    if (!text) return line;
    const after = start + visibleWidth(text);
    return `${sliceByColumn(line, 0, start)}\u001b[7m${text}\u001b[27m${sliceByColumn(line, after, Math.max(0, visibleWidth(line) - after))}`;
  }

  // The web link at a cell within the chat, as last drawn, or null.
  linkAt(row: number, column: number): string | null {
    const line = this.shown[row];
    return line === undefined ? null : linkAt(line, column);
  }

  // A click on a tool group, by row within the chat, opens or closes it; false when it hit something else.
  toggleAt(row: number): boolean {
    const id = this.groupAt(row);
    if (!id) return false;
    if (!this.expanded.delete(id)) this.expanded.add(id);
    return true;
  }

  // The pointer's row within the chat, or null once it leaves; true when the highlighted group changed.
  hoverAt(row: number | null): boolean {
    const id = this.groupAt(row);
    if (id === this.hovered) return false;
    this.hovered = id;
    return true;
  }

  isAtTop(): boolean {
    return this.scroll.scrollTop === 0;
  }

  scrollBy(lines: number): void {
    this.scroll.scrollBy(lines);
  }

  scrollToEnd(): void {
    this.scroll.scrollToEnd();
  }
}

// Draws floating rows, such as composer suggestions, over the bottom of the chat instead of pushing it up.
export function overlayBottom(lines: string[], popup: string[]): string[] {
  if (popup.length === 0) return lines;
  const shown = popup.slice(-lines.length);
  return [...lines.slice(0, lines.length - shown.length), ...shown];
}
