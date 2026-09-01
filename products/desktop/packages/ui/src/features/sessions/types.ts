import type { SessionUpdate } from "@agentclientprotocol/sdk";
import type {
  AgentContent,
  AgentToolCall,
  AgentToolCallContent,
  AgentToolCallLocation,
  AgentToolKind,
} from "@posthog/shared";

export type CodeToolKind = AgentToolKind;
export type ToolCallContent = AgentToolCallContent;
export type { SessionUpdate };

export interface ToolCall extends Omit<AgentToolCall, "id" | "parentId"> {
  _meta?: { [key: string]: unknown } | null;
  toolCallId: string;
}

type ConversationContentUpdate = {
  _meta?: { [key: string]: unknown } | null;
  content: AgentContent;
} & (
  | { sessionUpdate: "user_message_chunk" }
  | { sessionUpdate: "agent_message_chunk" }
  | { sessionUpdate: "agent_thought_chunk" }
);

interface ConversationToolCallUpdate
  extends Partial<
    Omit<AgentToolCall, "id" | "parentId" | "content" | "locations" | "title">
  > {
  _meta?: { [key: string]: unknown } | null;
  content?: AgentToolCallContent[] | null;
  locations?: AgentToolCallLocation[] | null;
  sessionUpdate: "tool_call_update";
  title?: string | null;
  toolCallId: string;
}

export type ConversationSessionUpdate =
  | Exclude<
      SessionUpdate,
      {
        sessionUpdate:
          | "user_message_chunk"
          | "agent_message_chunk"
          | "agent_thought_chunk"
          | "tool_call"
          | "tool_call_update";
      }
    >
  | ConversationContentUpdate
  | (ToolCall & { sessionUpdate: "tool_call" })
  | ConversationToolCallUpdate;

export type Plan = Extract<SessionUpdate, { sessionUpdate: "plan" }>;
export interface CompactBoundaryMetadata {
  trigger?: "manual" | "auto";
  preTokens?: number;
  contextSize?: number;
}

export interface CompactBoundaryUpdate extends CompactBoundaryMetadata {
  sessionUpdate: "compact_boundary";
}
