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
  stripTerminalSequences,
  Text,
} from "@earendil-works/pi-tui";
import type { TranscriptLine } from "./transcript";

// Shell-integration prompt marks (OSC 133) that pi emits for its own screen.
const PROMPT_MARKS = new RegExp(`${"\u001b"}\\]133;[A-Z]${"\u0007"}`, "g");
const DIM = (text: string): string => `\u001b[2m${text}\u001b[22m`;
const TOOL_MARKS: Record<string, string> = {
  completed: "\u001b[32m●\u001b[39m",
  failed: "\u001b[31m●\u001b[39m",
  in_progress: "\u001b[33m●\u001b[39m",
};
const OLDER_ROW = "older";
const SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

export interface ChatNotice {
  text: string;
  tone: "working" | "error";
}

// The run's status line; a working one spins, advancing with the clock on each repaint.
class NoticeRow implements Component {
  constructor(private readonly notice: ChatNotice) {}

  render(): string[] {
    if (this.notice.tone === "error") {
      return [` \u001b[31m${this.notice.text}\u001b[39m`];
    }
    const frame = SPINNER[Math.floor(Date.now() / 80) % SPINNER.length];
    return [DIM(` ${frame} ${this.notice.text}`)];
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

// Each change between user, tool and agent blocks gets one blank line.
const needsGap = (
  previous: TranscriptLine | undefined,
  line: TranscriptLine,
): boolean => previous !== undefined && previous.kind !== line.kind;

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
    case "tool":
      return new Text(
        `${TOOL_MARKS[line.status] ?? DIM("●")} ${DIM(line.title)}`,
        1,
        0,
      );
    case "notice":
      return new Text(DIM(line.text), 1, 0);
  }
}

// One pane's chat: pi's message components inside pi's ScrollView, clipped to the pane by us.
export class ChatView {
  private items: { id: string; component: Component }[] = [];
  private readonly scroll = new ScrollView(new Container(), { follow: "end" });
  // The message at the top of the screen, so new history above it does not move the reader.
  private anchor: { id: string; within: number } | null = null;
  private transcriptChanged = false;

  setTranscript(
    lines: TranscriptLine[],
    {
      hasOlder = false,
      notice = null,
    }: { hasOlder?: boolean; notice?: ChatNotice | null } = {},
  ): void {
    this.items = lines.flatMap((line, index) => {
      const item = { id: line.id, component: new Trimmed(componentFor(line)) };
      return needsGap(lines[index - 1], line)
        ? [{ id: `${line.id}:gap`, component: new Spacer(1) }, item]
        : [item];
    });
    if (notice) {
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
    for (const { id, component } of this.items) {
      starts.set(id, content.length);
      content.push(...component.render(contentWidth));
    }
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
    const visible = content
      .slice(top, top + height)
      // Ink gives an empty string no height, so blank lines carry a space.
      .map((line) => line.replace(PROMPT_MARKS, "") || " ");
    return [...visible, ...Array<string>(height - visible.length).fill(" ")];
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
