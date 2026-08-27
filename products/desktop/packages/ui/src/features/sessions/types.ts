import type { SessionUpdate } from "@agentclientprotocol/sdk";
import type {
  AgentContent,
  AgentToolCall,
  AgentToolCallContent,
  AgentToolCallLocation,
  AgentToolCallStatus,
  AgentToolKind,
} from "@posthog/shared";

export type CodeToolKind = AgentToolKind;
export type ToolCallContent = AgentToolCallContent;
export type ToolCallStatus = AgentToolCallStatus;
export type ToolCallLocation = AgentToolCallLocation;
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

interface ConversationToolCallUpdate {
  _meta?: { [key: string]: unknown } | null;
  content?: AgentToolCallContent[] | null;
  kind?: AgentToolKind | null;
  locations?: AgentToolCallLocation[] | null;
  rawInput?: unknown;
  rawOutput?: unknown;
  sessionUpdate: "tool_call_update";
  status?: AgentToolCallStatus | null;
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
export type ConfigOptionUpdate = Extract<
  SessionUpdate,
  { sessionUpdate: "config_option_update" }
>;

export interface CompactBoundaryMetadata {
  trigger?: "manual" | "auto";
  preTokens?: number;
  contextSize?: number;
}

export interface CompactBoundaryUpdate extends CompactBoundaryMetadata {
  sessionUpdate: "compact_boundary";
}
