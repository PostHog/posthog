/**
 * Resume - Restore agent state from persisted log
 *
 * Handles resuming a task from any point:
 * - Fetches log via the PostHog API
 * - Finds latest git_checkpoint event
 * - Rebuilds conversation from log events
 * - Restores working tree from checkpoint
 *
 * Uses Saga pattern for atomic operations with clear success/failure tracking.
 *
 * The log is the single source of truth for:
 * - Conversation history (user_message, agent_message_chunk, tool_call, tool_result)
 * - Working tree state (git_checkpoint events)
 * - Session metadata (device info, mode changes)
 */

import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { NativeGoalState } from "./acp-extensions";
import { selectRecentTurns } from "./adapters/claude/session/jsonl-hydration";
import type { PostHogAPIClient } from "./posthog-api";
import { ResumeSaga } from "./sagas/resume-saga";
import type { DeviceInfo, GitCheckpointEvent } from "./types";
import { Logger } from "./utils/logger";

export interface ResumeState {
  conversation: ConversationTurn[];
  latestGitCheckpoint: GitCheckpointEvent | null;
  interrupted: boolean;
  lastDevice?: DeviceInfo;
  logEntryCount: number;
  sessionId: string | null;
  nativeGoal?: NativeGoalState | null;
}

export interface ConversationTurn {
  role: "user" | "assistant";
  content: ContentBlock[];
  toolCalls?: ToolCallInfo[];
}

export interface ToolCallInfo {
  toolCallId: string;
  toolName: string;
  input: unknown;
  result?: unknown;
}

export interface ResumeConfig {
  taskId: string;
  runId: string;
  repositoryPath?: string;
  apiClient: PostHogAPIClient;
  logger?: Logger;
}

/**
 * Resume a task from its persisted log.
 * Returns the rebuilt state for the agent to continue from.
 * Checkpoint application happens in the agent server after SSE connects.
 */
export async function resumeFromLog(
  config: ResumeConfig,
): Promise<ResumeState> {
  const logger =
    config.logger || new Logger({ debug: false, prefix: "[Resume]" });

  logger.info("Resuming from log", {
    taskId: config.taskId,
    runId: config.runId,
  });

  const saga = new ResumeSaga(logger);

  const result = await saga.run({
    taskId: config.taskId,
    runId: config.runId,
    repositoryPath: config.repositoryPath,
    apiClient: config.apiClient,
    logger,
  });

  if (!result.success) {
    logger.error("Failed to resume from log", {
      error: result.error,
      failedStep: result.failedStep,
    });
    throw new Error(
      `Failed to resume at step '${result.failedStep}': ${result.error}`,
    );
  }

  return {
    conversation: result.data.conversation as ConversationTurn[],
    latestGitCheckpoint: result.data.latestGitCheckpoint,
    interrupted: result.data.interrupted,
    lastDevice: result.data.lastDevice,
    logEntryCount: result.data.logEntryCount,
    sessionId: result.data.sessionId,
    nativeGoal: result.data.nativeGoal,
  };
}

/**
 * Convert resumed conversation back to API format for continuation.
 */
export function conversationToPromptHistory(
  conversation: ConversationTurn[],
): Array<{ role: "user" | "assistant"; content: ContentBlock[] }> {
  return conversation.map((turn) => ({
    role: turn.role,
    content: turn.content,
  }));
}

const RESUME_HISTORY_TOKEN_BUDGET = 50_000;
const TOOL_RESULT_MAX_CHARS = 2000;

const RESUME_CONTEXT_MARKERS = [
  "You are resuming a previous conversation",
  "Here is the conversation history from the",
  "Continue from where you left off",
];

function isResumeContextTurn(turn: ConversationTurn): boolean {
  if (turn.role !== "user") return false;
  const text = turn.content
    .filter((b) => b.type === "text")
    .map((b) => (b as { type: "text"; text: string }).text)
    .join("");
  return RESUME_CONTEXT_MARKERS.some((marker) => text.includes(marker));
}

export function formatConversationForResume(
  conversation: ConversationTurn[],
): string {
  const filtered = conversation.filter((turn) => !isResumeContextTurn(turn));
  const selected = selectRecentTurns(filtered, RESUME_HISTORY_TOKEN_BUDGET);
  const parts: string[] = [];

  if (selected.length < filtered.length) {
    parts.push(
      `*(${filtered.length - selected.length} earlier turns omitted)*`,
    );
  }

  for (const turn of selected) {
    const role = turn.role === "user" ? "User" : "Assistant";

    const textParts = turn.content
      .filter((block) => block.type === "text")
      .map((block) => (block as { type: "text"; text: string }).text);

    if (textParts.length > 0) {
      parts.push(`**${role}**: ${textParts.join("\n")}`);
    }

    if (turn.toolCalls?.length) {
      const toolSummary = turn.toolCalls
        .map((tc) => {
          let resultStr = "";
          if (tc.result !== undefined) {
            const raw =
              typeof tc.result === "string"
                ? tc.result
                : JSON.stringify(tc.result);
            resultStr =
              raw.length > TOOL_RESULT_MAX_CHARS
                ? ` → ${raw.substring(0, TOOL_RESULT_MAX_CHARS)}...(truncated)`
                : ` → ${raw}`;
          }
          return `  - ${tc.toolName}${resultStr}`;
        })
        .join("\n");
      parts.push(`**${role} (tools)**:\n${toolSummary}`);
    }
  }

  return parts.join("\n\n");
}
