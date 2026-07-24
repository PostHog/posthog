import type { OutputMode } from "./args";

export interface FinishResult {
  stopReason: string;
  usage?: unknown;
  sessionId: string;
}

export interface OutputSink {
  onSessionUpdate(notification: unknown): void;
  finish(result: FinishResult): void;
}

interface WritableLike {
  write(chunk: string): unknown;
}

function extractChunkText(notification: unknown): string | undefined {
  const update = (notification as { update?: unknown } | undefined)?.update as
    | { sessionUpdate?: string; content?: { type?: string; text?: unknown } }
    | undefined;
  if (update?.sessionUpdate !== "agent_message_chunk") return undefined;
  if (update.content?.type !== "text") return undefined;
  return typeof update.content.text === "string"
    ? update.content.text
    : undefined;
}

/**
 * Routes assistant output to stdout. "text" streams each agent_message_chunk
 * as it arrives; "json" buffers and emits one JSON document on finish.
 */
export function createOutputSink(
  mode: OutputMode,
  stdout: WritableLike,
): OutputSink {
  const chunks: string[] = [];
  let streamedText = false;

  return {
    onSessionUpdate(notification) {
      const text = extractChunkText(notification);
      if (text === undefined) return;
      if (mode === "text") {
        stdout.write(text);
        streamedText = true;
      } else {
        chunks.push(text);
      }
    },
    finish({ stopReason, usage, sessionId }) {
      if (mode === "json") {
        stdout.write(
          `${JSON.stringify({ text: chunks.join(""), stopReason, usage, sessionId })}\n`,
        );
      } else if (streamedText) {
        stdout.write("\n");
      }
    },
  };
}
