import type { JsonRpcMessage, StoredLogEntry } from "@posthog/shared";

export type PortableSessionToolCallStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | null;

export interface PortableSessionUpdate {
  sessionUpdate?: string;
  content?: { type: string; text: string };
  attachments?: Array<{
    kind: "image" | "document";
    uri: string;
    fileName: string;
    mimeType?: string;
  }>;
  title?: string;
  toolCallId?: string;
  status?: PortableSessionToolCallStatus;
  rawInput?: Record<string, unknown>;
  rawOutput?: unknown;
  entries?: Array<{
    content: string;
    status: "pending" | "in_progress" | "completed" | "failed";
    priority: string;
  }>;
  _meta?: {
    claudeCode?: {
      toolName?: string;
      parentToolCallId?: string;
    };
  };
}

export interface PortableSessionNotification {
  update?: PortableSessionUpdate;
}

export interface PortableSessionAcpMessage {
  type: "acp_message";
  direction: "client" | "agent";
  ts: number;
  message: JsonRpcMessage;
}

export interface PortableSessionUpdateEvent {
  type: "session_update";
  ts: number;
  notification: PortableSessionNotification;
}

export type PortableSessionEvent =
  | PortableSessionAcpMessage
  | PortableSessionUpdateEvent;

export function inferStoredLogEntryDirection(
  entry: StoredLogEntry,
): "client" | "agent" {
  const message = entry.notification;
  if (!message) return "agent";
  if (message.id !== undefined && message.method !== undefined) return "client";
  return "agent";
}

export function convertStoredEntriesToPortableSessionEvents(
  entries: readonly StoredLogEntry[],
): PortableSessionEvent[] {
  const events: PortableSessionEvent[] = [];

  for (const entry of entries) {
    const ts = entry.timestamp
      ? new Date(entry.timestamp).getTime()
      : Date.now();

    events.push({
      type: "acp_message",
      direction: inferStoredLogEntryDirection(entry),
      ts,
      message: (entry.notification ?? {}) as JsonRpcMessage,
    });

    if (
      entry.type === "notification" &&
      entry.notification?.method === "session/update" &&
      entry.notification.params
    ) {
      events.push({
        type: "session_update",
        ts,
        notification: entry.notification.params as PortableSessionNotification,
      });
    }
  }

  return events;
}
