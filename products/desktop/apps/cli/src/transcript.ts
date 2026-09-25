import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";

export type TranscriptItem =
  | { id: string; kind: "user" | "assistant"; text: string }
  | {
      id: string;
      kind: "tool";
      name: string;
      state: "running" | "completed" | "failed";
    }
  | { id: string; kind: "status" | "error"; text: string };

function messageText(message: AgentMessage): string {
  if (message.role !== "user" && message.role !== "assistant") {
    return "";
  }

  if (typeof message.content === "string") {
    return message.content;
  }

  return message.content
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("");
}

function appendStatus(
  transcript: readonly TranscriptItem[],
  id: string,
  text: string,
): TranscriptItem[] {
  return [...transcript, { id, kind: "status", text }];
}

function appendAssistantError(
  transcript: readonly TranscriptItem[],
  message: AgentMessage,
): TranscriptItem[] {
  if (message.role !== "assistant" || message.stopReason !== "error") {
    return [...transcript];
  }

  return [
    ...transcript,
    {
      id: `error-${transcript.length}`,
      kind: "error",
      text: "The request failed. Check hog /login, then try again.",
    },
  ];
}

function projectMessageEnd(
  transcript: readonly TranscriptItem[],
  message: AgentMessage,
): TranscriptItem[] {
  if (message.role === "user") {
    const text = messageText(message);
    return text
      ? [...transcript, { id: `user-${message.timestamp}`, kind: "user", text }]
      : [...transcript];
  }

  if (message.role !== "assistant") {
    return [...transcript];
  }

  const id = `assistant-${message.timestamp}`;
  const text = messageText(message);
  const existingIndex = transcript.findIndex((item) => item.id === id);
  const projected = [...transcript];

  if (text) {
    if (existingIndex === -1) {
      projected.push({ id, kind: "assistant", text });
    } else {
      projected[existingIndex] = { id, kind: "assistant", text };
    }
  }

  return appendAssistantError(projected, message);
}

export function projectTranscriptEvent(
  transcript: readonly TranscriptItem[],
  event: AgentSessionEvent,
): TranscriptItem[] {
  if (event.type === "message_update") {
    const update = event.assistantMessageEvent;
    if (update.type !== "text_delta" || !update.delta) {
      return [...transcript];
    }

    const id = `assistant-${event.message.timestamp}`;
    const existingIndex = transcript.findIndex((item) => item.id === id);
    if (existingIndex === -1) {
      return [...transcript, { id, kind: "assistant", text: update.delta }];
    }

    const projected = [...transcript];
    const existing = projected[existingIndex];
    if (!existing || existing.kind !== "assistant") {
      return projected;
    }
    projected[existingIndex] = {
      ...existing,
      text: `${existing.text}${update.delta}`,
    };
    return projected;
  }

  if (event.type === "message_end") {
    return projectMessageEnd(transcript, event.message);
  }

  if (event.type === "tool_execution_start") {
    return [
      ...transcript,
      {
        id: `tool-${event.toolCallId}`,
        kind: "tool",
        name: event.toolName,
        state: "running",
      },
    ];
  }

  if (event.type === "tool_execution_end") {
    const id = `tool-${event.toolCallId}`;
    const existingIndex = transcript.findIndex((item) => item.id === id);
    const tool = {
      id,
      kind: "tool" as const,
      name: event.toolName,
      state: event.isError ? ("failed" as const) : ("completed" as const),
    };

    if (existingIndex === -1) {
      return [...transcript, tool];
    }

    const projected = [...transcript];
    projected[existingIndex] = tool;
    return projected;
  }

  if (event.type === "compaction_start") {
    return appendStatus(
      transcript,
      `status-${transcript.length}`,
      "Compacting context",
    );
  }

  if (event.type === "compaction_end") {
    return appendStatus(
      transcript,
      `status-${transcript.length}`,
      event.errorMessage ? "Context compaction failed" : "Context compacted",
    );
  }

  if (event.type === "auto_retry_start") {
    return appendStatus(
      transcript,
      `status-${transcript.length}`,
      `Retrying request (${event.attempt} of ${event.maxAttempts})`,
    );
  }

  if (event.type === "auto_retry_end" && !event.success) {
    return appendTranscriptError(
      transcript,
      "The request could not be retried. Check your connection and hog /login.",
    );
  }

  if (event.type === "summarization_retry_scheduled") {
    return appendStatus(
      transcript,
      `status-${transcript.length}`,
      `Retrying summary (${event.attempt} of ${event.maxAttempts})`,
    );
  }

  return [...transcript];
}

export function appendTranscriptError(
  transcript: readonly TranscriptItem[],
  text: string,
): TranscriptItem[] {
  return [
    ...transcript,
    { id: `error-${transcript.length}`, kind: "error", text },
  ];
}

export function projectSessionMessages(
  messages: readonly AgentMessage[],
): TranscriptItem[] {
  return messages.reduce<TranscriptItem[]>(
    (transcript, message) => projectMessageEnd(transcript, message),
    [],
  );
}
