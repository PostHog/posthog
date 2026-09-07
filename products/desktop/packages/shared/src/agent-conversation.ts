export type AgentToolKind =
  | "read"
  | "list"
  | "edit"
  | "delete"
  | "move"
  | "search"
  | "execute"
  | "think"
  | "fetch"
  | "switch_mode"
  | "question"
  | "other";

export type AgentToolCallStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed";

export type AgentProgressStatus = "in_progress" | "completed" | "failed";

/** Progress step the tasks backend reports for a message it tried to hand to the agent. */
export const FOLLOWUP_DELIVERY_PROGRESS_STEP = "followup_delivery";

export interface AgentTurnUsage {
  inputTokens: number;
  outputTokens: number;
  cachedReadTokens: number;
  cachedWriteTokens: number;
  thoughtTokens?: number;
  totalTokens: number;
  contextTokens?: number | null;
  contextWindow?: number;
}

export interface AgentTextContent {
  type: "text";
  text: string;
}

export interface AgentImageContent {
  type: "image";
  data: string;
  mimeType: string;
  fileName?: string;
}

export interface AgentAudioContent {
  type: "audio";
  data: string;
  mimeType: string;
}

export interface AgentResourceLinkContent {
  type: "resource_link";
  uri: string;
  name: string;
  description?: string | null;
  mimeType?: string | null;
  size?: number | null;
  title?: string | null;
}

interface AgentTextResource {
  uri: string;
  mimeType?: string | null;
  text: string;
}

interface AgentBlobResource {
  uri: string;
  mimeType?: string | null;
  blob: string;
}

export interface AgentEmbeddedResourceContent {
  type: "resource";
  resource: AgentTextResource | AgentBlobResource;
}

export type AgentContent =
  | AgentTextContent
  | AgentImageContent
  | AgentAudioContent
  | AgentResourceLinkContent
  | AgentEmbeddedResourceContent;

export interface AgentToolCallContentBlock {
  type: "content";
  content: AgentContent;
}

export interface AgentToolCallDiff {
  type: "diff";
  path: string;
  oldText?: string | null;
  newText: string;
}

export interface AgentToolCallTerminal {
  type: "terminal";
  terminalId: string;
}

export type AgentToolCallContent =
  | AgentToolCallContentBlock
  | AgentToolCallDiff
  | AgentToolCallTerminal;

export interface AgentToolCallLocation {
  path: string;
  line?: number | null;
}

export interface AgentToolCall {
  id: string;
  title: string;
  kind?: AgentToolKind | null;
  status?: AgentToolCallStatus | null;
  content?: AgentToolCallContent[];
  locations?: AgentToolCallLocation[];
  rawInput?: unknown;
  rawOutput?: unknown;
  details?: unknown;
  parentId?: string;
  origin?: "agent" | "user_shell";
}

interface AgentConversationEventIdentity {
  sourceId?: string;
}

export type AgentConversationEvent = (
  | {
      type: "user_message";
      id: string;
      timestamp: number;
      content: AgentContent[];
    }
  | {
      type: "assistant_message_chunk";
      timestamp: number;
      content: AgentContent;
    }
  | {
      type: "assistant_thought_chunk";
      timestamp: number;
      content: AgentContent;
    }
  | {
      type: "tool_call_started";
      timestamp: number;
      toolCall: AgentToolCall;
    }
  | {
      type: "tool_call_updated";
      timestamp: number;
      toolCall: Pick<AgentToolCall, "id"> & Partial<Omit<AgentToolCall, "id">>;
    }
  | {
      type: "progress";
      timestamp: number;
      step: string;
      status: AgentProgressStatus;
      label: string;
      group: string;
      detail?: string;
    }
  | {
      type: "queue_update";
      timestamp: number;
      steering: string[];
      followUp: string[];
    }
  | {
      type: "runtime_status";
      timestamp: number;
      status: string;
      isComplete?: boolean;
      error?: string;
      message?: string;
      attempt?: number;
      maxAttempts?: number;
      delayMs?: number;
    }
  | {
      type: "runtime_error";
      timestamp: number;
      errorType: string;
      message: string;
    }
  | {
      type: "turn_completed";
      timestamp: number;
      stopReason?: string;
      totalTokens?: number;
      usage?: AgentTurnUsage;
    }
) &
  AgentConversationEventIdentity;

/**
 * Whether a progress event says a message never reached the agent.
 *
 * The turn a message starts is optimistic: the client marks the session busy
 * when the backend accepts the message, before the sandbox has it. A failed
 * delivery is therefore the only signal that no turn is running, and the run
 * stays alive, so nothing else arrives to end it.
 */
export function isFailedFollowupDelivery(
  event: AgentConversationEvent,
): boolean {
  return (
    event.type === "progress" &&
    event.step === FOLLOWUP_DELIVERY_PROGRESS_STEP &&
    event.status === "failed"
  );
}
