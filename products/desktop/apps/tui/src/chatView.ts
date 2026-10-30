import type { AssistantMessage } from "@earendil-works/pi-ai";
import {
  AssistantMessageComponent,
  getMarkdownTheme,
  UserMessageComponent,
} from "@earendil-works/pi-coding-agent";
import { Container, ScrollView, Text } from "@earendil-works/pi-tui";
import type { TranscriptLine } from "./transcript";

// Shell-integration prompt marks (OSC 133) that pi emits for its own screen.
const PROMPT_MARKS = new RegExp(`${"\u001b"}\\]133;[A-Z]${"\u0007"}`, "g");
const DIM = (text: string): string => `\u001b[2m${text}\u001b[22m`;
const TOOL_MARKS: Record<string, string> = {
  completed: "\u001b[32m●\u001b[39m",
  failed: "\u001b[31m●\u001b[39m",
  in_progress: "\u001b[33m●\u001b[39m",
};

function assistantMessage(text: string): AssistantMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    stopReason: "stop",
    timestamp: 0,
  } as AssistantMessage;
}

// One pane's chat: pi's message components inside pi's ScrollView, clipped to the pane by us.
export class ChatView {
  private readonly messages = new Container();
  private readonly scroll = new ScrollView(this.messages, { follow: "end" });

  setTranscript(lines: TranscriptLine[]): void {
    this.messages.clear();
    const markdown = getMarkdownTheme();
    for (const line of lines) {
      switch (line.kind) {
        case "user":
          this.messages.addChild(new UserMessageComponent(line.text, markdown));
          break;
        case "assistant":
          this.messages.addChild(
            new AssistantMessageComponent(
              assistantMessage(line.text),
              false,
              markdown,
            ),
          );
          break;
        case "tool":
          this.messages.addChild(
            new Text(
              `${TOOL_MARKS[line.status] ?? DIM("●")} ${DIM(line.title)}`,
              1,
              0,
            ),
          );
          break;
        case "notice":
          this.messages.addChild(new Text(DIM(line.text), 1, 0));
          break;
      }
    }
  }

  render(width: number, height: number): string[] {
    const content = this.scroll.render(width);
    this.scroll.updateLayout(content.length, height, () => {});
    const top = this.scroll.scrollTop;
    const visible = content
      .slice(top, top + height)
      .map((line) => line.replace(PROMPT_MARKS, ""));
    return [...visible, ...Array<string>(height - visible.length).fill("")];
  }

  scrollBy(lines: number): void {
    this.scroll.scrollBy(lines);
  }

  scrollToEnd(): void {
    this.scroll.scrollToEnd();
  }
}
