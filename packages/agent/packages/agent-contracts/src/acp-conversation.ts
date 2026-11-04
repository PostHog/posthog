import type {
  AgentContent,
  AgentConversationEvent,
  AgentToolCall,
} from "./agent-conversation";

export const PI_EXTENSION_META_KEY = "piExtension";

export type AcpToolCallSessionUpdate = {
  sessionUpdate: "tool_call" | "tool_call_update";
  toolCallId: string;
} & Record<string, unknown>;

export type AcpConversationSessionUpdate =
  | {
      sessionUpdate: "agent_message_chunk" | "agent_thought_chunk";
      content: unknown;
    }
  | AcpToolCallSessionUpdate;

export interface AcpConversationNotification {
  method: string;
  params: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function definedFields(
  fields: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(fields).filter(
      ([, value]) => value !== undefined && value !== null,
    ),
  );
}

function toolCallSessionUpdate(
  sessionUpdate: AcpToolCallSessionUpdate["sessionUpdate"],
  toolCall: Partial<AgentToolCall>,
): AcpToolCallSessionUpdate | null {
  const { id, parentId, ...fields } = toolCall;
  if (typeof id !== "string" || !id) {
    return null;
  }
  const update: AcpToolCallSessionUpdate = {
    sessionUpdate,
    toolCallId: id,
    ...definedFields(fields),
  };
  if (parentId) {
    const meta = fields._meta ?? {};
    const claudeCode = isRecord(meta.claudeCode) ? meta.claudeCode : {};
    update._meta = {
      ...meta,
      claudeCode: { ...claudeCode, parentToolCallId: parentId },
    };
  }
  return update;
}

function toolCallFromSessionUpdate(
  update: Record<string, unknown>,
): Record<string, unknown> | null {
  const { sessionUpdate: _sessionUpdate, toolCallId, ...fields } = update;
  if (typeof toolCallId !== "string" || !toolCallId) {
    return null;
  }
  const toolCall: Record<string, unknown> = { ...fields, id: toolCallId };
  if (toolCall.title === undefined && typeof fields.name === "string") {
    toolCall.title = fields.name;
  }
  const meta = isRecord(fields._meta) ? fields._meta : null;
  const claudeCode = meta && isRecord(meta.claudeCode) ? meta.claudeCode : null;
  if (meta && claudeCode && typeof claudeCode.parentToolCallId === "string") {
    toolCall.parentId = claudeCode.parentToolCallId;
    const { parentToolCallId: _parentToolCallId, ...otherClaudeCode } =
      claudeCode;
    const { claudeCode: _claudeCode, ...otherMeta } = meta;
    const restoredMeta =
      Object.keys(otherClaudeCode).length > 0
        ? { ...otherMeta, claudeCode: otherClaudeCode }
        : otherMeta;
    if (Object.keys(restoredMeta).length > 0) {
      toolCall._meta = restoredMeta;
    } else {
      delete toolCall._meta;
    }
  }
  return toolCall;
}

export function agentConversationEventToSessionUpdate(
  event: AgentConversationEvent,
): AcpConversationSessionUpdate | null {
  switch (event.type) {
    case "assistant_message_chunk":
      return { sessionUpdate: "agent_message_chunk", content: event.content };
    case "assistant_thought_chunk":
      return { sessionUpdate: "agent_thought_chunk", content: event.content };
    case "tool_call_started":
      return toolCallSessionUpdate("tool_call", event.toolCall);
    case "tool_call_updated":
      return toolCallSessionUpdate("tool_call_update", event.toolCall);
    default:
      return null;
  }
}

export function agentConversationEventToAcpNotification(
  event: AgentConversationEvent,
): AcpConversationNotification | null {
  const update = agentConversationEventToSessionUpdate(event);
  if (update) {
    return { method: "session/update", params: { update } };
  }
  switch (event.type) {
    case "user_message":
      return {
        method: "_posthog/user_message",
        params: { content: event.content, messageId: event.id },
      };
    case "progress":
      return {
        method: "_posthog/progress",
        params: definedFields({
          step: event.step,
          status: event.status,
          label: event.label,
          group: event.group,
          detail: event.detail,
        }),
      };
    case "runtime_status":
      return {
        method: "_posthog/status",
        params: {
          ...definedFields({
            status: event.status,
            error: event.error,
            message: event.message,
            attempt: event.attempt,
            maxAttempts: event.maxAttempts,
            delayMs: event.delayMs,
          }),
          isComplete: event.isComplete === true,
        },
      };
    case "runtime_error":
      return {
        method: "_posthog/error",
        params: { message: event.message, errorType: event.errorType },
      };
    case "turn_completed":
      return {
        method: "_posthog/turn_complete",
        params: definedFields({
          stopReason:
            event.stopReason === "aborted" ? "cancelled" : event.stopReason,
          usage: event.usage,
          totalTokens: event.totalTokens,
        }),
      };
    case "queue_update":
      return {
        method: "_posthog/pi_queue_update",
        params: { steering: event.steering, followUp: event.followUp },
      };
    default:
      return null;
  }
}

export function readPiExtensionMessage(
  params: unknown,
): Record<string, unknown> | null {
  const meta = isRecord(params) ? params._meta : undefined;
  const message = isRecord(meta) ? meta[PI_EXTENSION_META_KEY] : undefined;
  return isRecord(message) ? message : null;
}

export function acpNotificationToAgentConversationEvent(
  notification: AcpConversationNotification,
  timestamp: number,
): AgentConversationEvent | null {
  const { method, params } = notification;
  if (readPiExtensionMessage(params)) {
    return null;
  }
  switch (method) {
    case "session/update": {
      const update = params.update;
      if (!isRecord(update)) {
        return null;
      }
      switch (update.sessionUpdate) {
        case "agent_message":
        case "agent_message_chunk":
          return {
            type: "assistant_message_chunk",
            timestamp,
            content: update.content as AgentContent,
          };
        case "agent_thought_chunk":
          return {
            type: "assistant_thought_chunk",
            timestamp,
            content: update.content as AgentContent,
          };
        case "tool_call": {
          const toolCall = toolCallFromSessionUpdate(update);
          return toolCall
            ? {
                type: "tool_call_started",
                timestamp,
                toolCall: toolCall as unknown as AgentToolCall,
              }
            : null;
        }
        case "tool_call_update": {
          const toolCall = toolCallFromSessionUpdate(update);
          return toolCall
            ? {
                type: "tool_call_updated",
                timestamp,
                toolCall: toolCall as unknown as AgentToolCall,
              }
            : null;
        }
        default:
          return null;
      }
    }
    case "_posthog/user_message":
      return {
        type: "user_message",
        id: typeof params.messageId === "string" ? params.messageId : "",
        timestamp,
        content: Array.isArray(params.content)
          ? (params.content as AgentContent[])
          : [],
      };
    case "_posthog/progress":
      return {
        ...params,
        type: "progress",
        timestamp,
      } as AgentConversationEvent;
    case "_posthog/status":
      return {
        ...params,
        type: "runtime_status",
        timestamp,
      } as AgentConversationEvent;
    case "_posthog/error":
      return {
        type: "runtime_error",
        timestamp,
        errorType: String(params.errorType ?? ""),
        message: String(params.message ?? ""),
      };
    case "_posthog/turn_complete":
      return {
        ...params,
        type: "turn_completed",
        timestamp,
      } as AgentConversationEvent;
    case "_posthog/pi_queue_update":
      return {
        type: "queue_update",
        timestamp,
        steering: Array.isArray(params.steering)
          ? (params.steering as string[])
          : [],
        followUp: Array.isArray(params.followUp)
          ? (params.followUp as string[])
          : [],
      };
    default:
      return null;
  }
}
