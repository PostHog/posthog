export type AgentToolKind =
  | "read"
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

export interface AgentTextContent {
  type: "text";
  text: string;
}

export interface AgentImageContent {
  type: "image";
  data: string;
  mimeType: string;
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

export interface AgentTextResource {
  uri: string;
  mimeType?: string | null;
  text: string;
}

export interface AgentBlobResource {
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
  parentId?: string;
}

export type AgentConversationEvent =
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
    };
