import type { SessionNotification } from "@agentclientprotocol/sdk";
import type { OutputMode } from "./args";

export interface FinishResult {
  stopReason: string;
  usage?: unknown;
  sessionId: string;
}

export interface OutputSink {
  onSessionUpdate(notification: SessionNotification): void;
  finish(result: FinishResult): void;
}

interface WritableLike {
  write(chunk: string): unknown;
}

function extractChunkText(
  notification: SessionNotification,
): string | undefined {
  const { update } = notification;
  if (update.sessionUpdate !== "agent_message_chunk") return undefined;
  return update.content.type === "text" ? update.content.text : undefined;
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
