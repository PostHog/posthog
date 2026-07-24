import { AgentMessage } from "@posthog/ui/features/sessions/components/session-update/AgentMessage";
import { CompactBoundaryView } from "@posthog/ui/features/sessions/components/session-update/CompactBoundaryView";
import { ConsoleMessage } from "@posthog/ui/features/sessions/components/session-update/ConsoleMessage";
import { ErrorNotificationView } from "@posthog/ui/features/sessions/components/session-update/ErrorNotificationView";
import { ProgressGroupView } from "@posthog/ui/features/sessions/components/session-update/ProgressGroupView";
import { StatusNotificationView } from "@posthog/ui/features/sessions/components/session-update/StatusNotificationView";
import { TaskNotificationView } from "@posthog/ui/features/sessions/components/session-update/TaskNotificationView";
import { ThoughtView } from "@posthog/ui/features/sessions/components/session-update/ThoughtView";
import type {
  CompactBoundaryUpdate,
  ConversationSessionUpdate,
  ToolCall,
} from "@posthog/ui/features/sessions/types";
import type { Step } from "@posthog/ui/primitives/StepList";
import { memo } from "react";
import type { ConversationItem } from "../buildConversationItems";
import { ToolCallBlock } from "./ToolCallBlock";

export type RenderItem =
  | ConversationSessionUpdate
  | {
      sessionUpdate: "console";
      level: string;
      message: string;
      timestamp?: string;
    }
  | CompactBoundaryUpdate
  | {
      sessionUpdate: "status";
      status: string;
      isComplete?: boolean;
      /** Epoch ms a `compacting` status began; drives the elapsed timer. */
      startedAt?: number;
      /** Set when a status ends in failure (e.g. a failed compaction) so the row renders the error. */
      error?: string;
      /** Refusal statuses: display-only stop_details.explanation from the API. */
      explanation?: string;
      /** Refusal fallback: the model that declined the request. */
      fromModel?: string;
      /** Refusal fallback: the model that retried the request. */
      toModel?: string;
      message?: string;
      attempt?: number;
      maxAttempts?: number;
      delayMs?: number;
    }
  | {
      sessionUpdate: "error";
      errorType: string;
      message: string;
    }
  | {
      sessionUpdate: "task_notification";
      taskId: string;
      status: "completed" | "failed" | "stopped";
      summary: string;
      outputFile: string;
    }
  | {
      sessionUpdate: "progress_group";
      steps: Step[];
      isActive: boolean;
    };

interface SessionUpdateViewProps {
  item: RenderItem;
  toolCalls?: Map<string, ToolCall>;
  childItems?: Map<string, ConversationItem[]>;
  turnCancelled?: boolean;
  turnComplete?: boolean;
  thoughtComplete?: boolean;
}

export const SessionUpdateView = memo(function SessionUpdateView({
  item,
  toolCalls,
  childItems,
  turnCancelled,
  turnComplete,
  thoughtComplete,
}: SessionUpdateViewProps) {
  switch (item.sessionUpdate) {
    case "user_message_chunk":
      return null;
    case "agent_message_chunk":
      return item.content.type === "text" ? (
        <AgentMessage
          content={item.content.text}
          isStreaming={turnComplete === false}
        />
      ) : null;
    case "agent_thought_chunk":
      return item.content.type === "text" ? (
        <ThoughtView content={item.content.text} isLoading={!thoughtComplete} />
      ) : null;
    case "tool_call":
      return (
        <ToolCallBlock
          toolCall={toolCalls?.get(item.toolCallId) ?? item}
          turnCancelled={turnCancelled}
          turnComplete={turnComplete}
          childItems={childItems?.get(item.toolCallId)}
          childItemsMap={childItems}
        />
      );
    case "tool_call_update":
      return null;
    case "plan":
      return null;
    case "available_commands_update":
      return null;
    case "config_option_update":
      return null;
    case "console":
      return (
        <ConsoleMessage
          level={item.level as "info" | "debug" | "warn" | "error"}
          message={item.message}
          timestamp={item.timestamp}
        />
      );
    case "compact_boundary":
      return (
        <CompactBoundaryView
          trigger={item.trigger}
          preTokens={item.preTokens}
          contextSize={item.contextSize}
        />
      );
    case "status":
      return (
        <StatusNotificationView
          status={item.status}
          isComplete={item.isComplete}
          startedAt={item.startedAt}
          error={item.error}
          explanation={item.explanation}
          fromModel={item.fromModel}
          toModel={item.toModel}
          message={item.message}
          attempt={item.attempt}
          maxAttempts={item.maxAttempts}
          delayMs={item.delayMs}
        />
      );
    case "error":
      return (
        <ErrorNotificationView
          errorType={item.errorType}
          message={item.message}
        />
      );
    case "task_notification":
      return (
        <TaskNotificationView status={item.status} summary={item.summary} />
      );
    case "progress_group":
      return (
        <ProgressGroupView
          steps={item.steps}
          isActive={item.isActive}
          turnComplete={turnComplete}
        />
      );
    default:
      return null;
  }
});
