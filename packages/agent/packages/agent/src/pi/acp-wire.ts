import {
  type AcpConversationNotification,
  type AgentConversationEvent,
  agentConversationEventToAcpNotification,
  MCP_TOOL_PERMISSION_OPTIONS,
  PI_EXTENSION_META_KEY,
  type StoredLogEntry,
} from "@posthog/agent-contracts";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import type { RpcExtensionUIResponse } from "./types";

const CONFIRM_OPTION_ID = "confirm";
const CANCEL_OPTION_ID = "cancel";
const PI_EXTENSION_EVENT_METHOD = "_posthog/pi_extension_event";

export const PI_ACP_MCP_PERMISSION_OPTIONS = [
  { kind: "allow_once", name: "Allow", optionId: "allow" },
  ...MCP_TOOL_PERMISSION_OPTIONS.map((option) =>
    option.kind === "reject_once"
      ? {
          ...option,
          _meta: { hint: "Blocks this tool call. The agent keeps working." },
        }
      : option,
  ),
];

export type PiExtensionDialogMethod = "select" | "confirm" | "input" | "editor";

export interface PiExtensionDialog {
  id: string;
  method: PiExtensionDialogMethod;
  options: string[];
  timeout?: number;
}

export interface PermissionAnswer {
  optionId: string;
  customInput?: string;
  answers?: Record<string, string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isDialogMethod(method: unknown): method is PiExtensionDialogMethod {
  return (
    method === "select" ||
    method === "confirm" ||
    method === "input" ||
    method === "editor"
  );
}

export function readPiExtensionDialog(
  message: Record<string, unknown>,
): PiExtensionDialog | null {
  const id = optionalString(message.id);
  if (
    message.type !== "extension_ui_request" ||
    !id ||
    !isDialogMethod(message.method)
  ) {
    return null;
  }
  return {
    id,
    method: message.method,
    options:
      message.method === "select" && Array.isArray(message.options)
        ? message.options.filter(
            (option): option is string =>
              typeof option === "string" && option !== "",
          )
        : [],
    ...(typeof message.timeout === "number" && message.timeout > 0
      ? { timeout: message.timeout }
      : {}),
  };
}

function withPiExtension(
  params: Record<string, unknown>,
  message: Record<string, unknown>,
): Record<string, unknown> {
  return { ...params, _meta: { [PI_EXTENSION_META_KEY]: message } };
}

function dialogRequest(
  message: Record<string, unknown>,
  dialog: PiExtensionDialog,
): AcpConversationNotification {
  if (dialog.method === "confirm") {
    const title =
      optionalString(message.title) ?? "The agent needs your confirmation";
    const detail = optionalString(message.message);
    return {
      method: POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST,
      params: withPiExtension(
        {
          requestId: dialog.id,
          toolCall: {
            toolCallId: `pi-extension-${dialog.id}`,
            kind: "other",
            description: detail ? `${title}\n\n${detail}` : title,
          },
          options: [
            {
              optionId: CONFIRM_OPTION_ID,
              name: "Confirm",
              kind: "allow_once",
            },
            {
              optionId: CANCEL_OPTION_ID,
              name: "Cancel",
              kind: "reject_once",
              _meta: {
                hint: "Declines this request. The agent keeps working.",
              },
            },
          ],
        },
        message,
      ),
    };
  }
  const title = optionalString(message.title) ?? "The agent needs your input";
  return {
    method: POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST,
    params: withPiExtension(
      {
        requestId: dialog.id,
        toolCall: {
          toolCallId: `pi-extension-${dialog.id}`,
          title,
          kind: "question",
          _meta: {
            codeToolKind: "question",
            questions: [
              {
                question: title,
                multiSelect: false,
                options: dialog.options.map((label) => ({ label })),
                ...(optionalString(message.placeholder)
                  ? { placeholder: message.placeholder }
                  : {}),
                ...(typeof message.prefill === "string"
                  ? { defaultAnswer: message.prefill }
                  : {}),
                ...(dialog.method === "editor" ? { multiline: true } : {}),
              },
            ],
          },
        },
        options:
          dialog.options.length > 0
            ? dialog.options.map((label, index) => ({
                optionId: `option_${index}`,
                name: label,
                kind: "allow_once",
              }))
            : [{ optionId: "option_0", name: "Submit", kind: "allow_once" }],
      },
      message,
    ),
  };
}

function extensionNotice(
  text: string,
  message: Record<string, unknown>,
): AcpConversationNotification {
  return {
    method: POSTHOG_NOTIFICATIONS.STATUS,
    params: withPiExtension(
      { status: "extension_notice", isComplete: true, message: text },
      message,
    ),
  };
}

export function piExtensionAcpNotification(
  message: Record<string, unknown>,
): AcpConversationNotification | null {
  if (message.type === "extension_ui_response") {
    const id = optionalString(message.id);
    return id
      ? {
          method: POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED,
          params: withPiExtension({ requestId: id }, message),
        }
      : null;
  }
  if (message.type === "extension_error") {
    const error = optionalString(message.error);
    if (!error) {
      return null;
    }
    const extension = optionalString(message.extensionPath)
      ?.split(/[\\/]/)
      .pop();
    const during = optionalString(message.event);
    return extensionNotice(
      extension
        ? `${extension} failed${during ? ` during ${during}` : ""}: ${error}`
        : error,
      message,
    );
  }
  if (message.type !== "extension_ui_request") {
    return null;
  }
  const dialog = readPiExtensionDialog(message);
  if (dialog) {
    return dialogRequest(message, dialog);
  }
  if (message.method === "notify") {
    const text = optionalString(message.message);
    if (!text) {
      return null;
    }
    const level = optionalString(message.notifyType) ?? "info";
    return level === "warning" || level === "error"
      ? extensionNotice(text, message)
      : {
          method: POSTHOG_NOTIFICATIONS.CONSOLE,
          params: withPiExtension({ message: text, level }, message),
        };
  }
  return {
    method: PI_EXTENSION_EVENT_METHOD,
    params: withPiExtension({}, message),
  };
}

export function piExtensionDialogResponse(
  dialog: PiExtensionDialog,
  answer: PermissionAnswer,
): RpcExtensionUIResponse {
  if (answer.optionId === CANCEL_OPTION_ID) {
    return { type: "extension_ui_response", id: dialog.id, cancelled: true };
  }
  if (dialog.method === "confirm") {
    return {
      type: "extension_ui_response",
      id: dialog.id,
      confirmed: answer.optionId === CONFIRM_OPTION_ID,
    };
  }
  const index = Number(answer.optionId.replace(/^option_/, ""));
  const chosen = Number.isInteger(index) ? dialog.options[index] : undefined;
  return {
    type: "extension_ui_response",
    id: dialog.id,
    value:
      Object.values(answer.answers ?? {})[0] ??
      answer.customInput ??
      chosen ??
      "",
  };
}

function conversationNotification(
  event: unknown,
): AcpConversationNotification | null {
  if (!isRecord(event)) {
    return null;
  }
  const notification = agentConversationEventToAcpNotification(
    event as unknown as AgentConversationEvent,
  );
  const update = notification?.params.update;
  if (isRecord(update) && update.title === update.name) {
    delete update.title;
  }
  return notification;
}

function entryNotification(
  entry: Record<string, unknown>,
): AcpConversationNotification | null | undefined {
  switch (entry.type) {
    case "pi_event":
      return conversationNotification(entry.event);
    case "pi_run_started":
      return {
        method: POSTHOG_NOTIFICATIONS.RUN_STARTED,
        params: {
          ...(typeof entry.runId === "string" ? { runId: entry.runId } : {}),
          ...(typeof entry.taskId === "string" ? { taskId: entry.taskId } : {}),
        },
      };
    case "pi_extension_event":
      return isRecord(entry.notification) && isRecord(entry.notification.params)
        ? piExtensionAcpNotification(entry.notification.params)
        : null;
    case "extension_ui_request":
    case "extension_ui_response":
    case "extension_error":
      return piExtensionAcpNotification(entry);
    default:
      return undefined;
  }
}

export function piAcpWireEntry(source: object): StoredLogEntry | null {
  const entry = source as Record<string, unknown>;
  const notification = entryNotification(entry);
  if (notification === undefined) {
    return source as StoredLogEntry;
  }
  if (!notification) {
    return null;
  }
  return {
    type: "notification",
    timestamp:
      typeof entry.timestamp === "string"
        ? entry.timestamp
        : new Date().toISOString(),
    ...(typeof entry.id === "string" ? { id: entry.id } : {}),
    ...(typeof entry.event_id === "string" ? { event_id: entry.event_id } : {}),
    ...(Array.isArray(entry.covered_event_ids)
      ? { covered_event_ids: entry.covered_event_ids as string[] }
      : {}),
    notification: { jsonrpc: "2.0", ...notification },
  } as StoredLogEntry;
}

function assistantChunkText(entry: Record<string, unknown>): string | null {
  if (
    entry.type !== "pi_event" ||
    !isRecord(entry.event) ||
    entry.event.type !== "assistant_message_chunk"
  ) {
    return null;
  }
  const content = entry.event.content;
  return isRecord(content) &&
    content.type === "text" &&
    typeof content.text === "string"
    ? content.text
    : null;
}

function agentMessageEntry(chunks: Record<string, unknown>[]): StoredLogEntry {
  const first = chunks[0];
  const last = chunks[chunks.length - 1];
  return {
    type: "notification",
    timestamp:
      typeof first.timestamp === "string"
        ? first.timestamp
        : new Date().toISOString(),
    ...(typeof first.id === "string" ? { id: first.id } : {}),
    ...(typeof last.event_id === "string" ? { event_id: last.event_id } : {}),
    ...(typeof first.event_id === "string"
      ? { first_event_id: first.event_id }
      : {}),
    notification: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message",
          content: {
            type: "text",
            text: chunks.map((chunk) => assistantChunkText(chunk)).join(""),
          },
        },
      },
    },
  } as StoredLogEntry;
}

export function piAcpLogEntries<T extends object>(
  entries: T[],
  { final }: { final: boolean },
): { wire: StoredLogEntry[]; carry: T[] } {
  const wire: StoredLogEntry[] = [];
  let chunks: T[] = [];
  for (const entry of entries) {
    if (assistantChunkText(entry as Record<string, unknown>) !== null) {
      chunks.push(entry);
      continue;
    }
    if (chunks.length > 0) {
      wire.push(agentMessageEntry(chunks as Record<string, unknown>[]));
      chunks = [];
    }
    const converted = piAcpWireEntry(entry);
    if (converted) {
      wire.push(converted);
    }
  }
  if (final && chunks.length > 0) {
    wire.push(agentMessageEntry(chunks as Record<string, unknown>[]));
    chunks = [];
  }
  return { wire, carry: chunks };
}
