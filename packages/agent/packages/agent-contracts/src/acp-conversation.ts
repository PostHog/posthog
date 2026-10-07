import type {
  AgentConversationEvent,
  AgentToolCall,
} from "./agent-conversation";

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

function toolCallSessionUpdate(
  sessionUpdate: AcpToolCallSessionUpdate["sessionUpdate"],
  toolCall: Partial<AgentToolCall>,
): AcpToolCallSessionUpdate | null {
  const { id, parentId, ...fields } = toolCall;
  if (typeof id !== "string" || !id) {
    return null;
  }
  const update: AcpToolCallSessionUpdate = { sessionUpdate, toolCallId: id };
  for (const [field, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) {
      update[field] = value;
    }
  }
  if (parentId) {
    const meta = fields._meta ?? {};
    const claudeCode =
      typeof meta.claudeCode === "object" && meta.claudeCode !== null
        ? meta.claudeCode
        : {};
    update._meta = {
      ...meta,
      claudeCode: { ...claudeCode, parentToolCallId: parentId },
    };
  }
  return update;
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
        params: { content: event.content },
      };
    case "progress":
      return {
        method: "_posthog/progress",
        params: {
          step: event.step,
          status: event.status,
          label: event.label,
          group: event.group,
          ...(event.detail !== undefined ? { detail: event.detail } : {}),
        },
      };
    case "runtime_status":
      return {
        method: "_posthog/status",
        params: {
          status: event.status,
          isComplete: event.isComplete === true,
          ...(event.error !== undefined ? { error: event.error } : {}),
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
        params: {
          stopReason:
            event.stopReason === "aborted" ? "cancelled" : event.stopReason,
          ...(event.usage ? { usage: event.usage } : {}),
        },
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
