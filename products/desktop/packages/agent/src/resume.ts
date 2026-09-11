/**
 * Resume - Restore agent state from persisted log
 *
 * Handles resuming a task from any point:
 * - Fetches log via the PostHog API
 * - Rebuilds conversation from log events
 *
 * Uses Saga pattern for atomic operations with clear success/failure tracking.
 *
 * The log is the single source of truth for:
 * - Conversation history (user_message, agent_message_chunk, tool_call, tool_result)
 * - Session metadata (device info, mode changes)
 */

import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { NativeGoalState } from "./acp-extensions";
import { selectRecentTurns } from "./adapters/claude/session/jsonl-hydration";
import type { PostHogAPIClient } from "./posthog-api";
import { ResumeSaga } from "./sagas/resume-saga";
import { Logger } from "./utils/logger";

export interface ResumeState {
  conversation: ConversationTurn[];
  interrupted: boolean;
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
    interrupted: result.data.interrupted,
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
const TOOL_NAME_MAX_CHARS = 120;

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

/**
 * The name the summary shows for one tool call, cut to a first-line preview.
 * A shell call carries no tool name of its own, so it arrives named after the
 * whole command — a heredoc can run to kilobytes across many lines.
 */
function renderToolName(toolName: string): string {
  const preview = toolName.split("\n", 1)[0].slice(0, TOOL_NAME_MAX_CHARS);
  return preview === toolName ? toolName : `${preview}...(truncated)`;
}

/** The result text the summary shows for one tool call, cut to the render cap. */
function renderToolResult(result: unknown): string {
  const raw = typeof result === "string" ? result : JSON.stringify(result);
  return raw.length > TOOL_RESULT_MAX_CHARS
    ? `${raw.substring(0, TOOL_RESULT_MAX_CHARS)}...(truncated)`
    : raw;
}

/**
 * Charge the history budget for what the summary renders. The summary shows a
 * previewed call name and a capped result and never the input, so estimating
 * the stored payloads instead sheds whole calls — and the turns around them —
 * that would have rendered in a few hundred characters.
 */
function withRenderedToolPayloads(turn: ConversationTurn): ConversationTurn {
  if (!turn.toolCalls?.length) return turn;
  return {
    ...turn,
    toolCalls: turn.toolCalls.map((tc) => ({
      ...tc,
      toolName: renderToolName(tc.toolName),
      input: undefined,
      result: tc.result === undefined ? undefined : renderToolResult(tc.result),
    })),
  };
}

export function formatConversationForResume(
  conversation: ConversationTurn[],
): string {
  const filtered = conversation
    .filter((turn) => !isResumeContextTurn(turn))
    .map(withRenderedToolPayloads);
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
          const resultStr =
            tc.result === undefined ? "" : ` → ${renderToolResult(tc.result)}`;
          return `  - ${renderToolName(tc.toolName)}${resultStr}`;
        })
        .join("\n");
      parts.push(`**${role} (tools)**:\n${toolSummary}`);
    }
  }

  return parts.join("\n\n");
}
