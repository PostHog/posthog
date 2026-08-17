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
import {
  capToolPayload,
  selectRecentTurns,
} from "./adapters/claude/session/jsonl-hydration";
import type { PostHogAPIClient } from "./posthog-api";
import { ResumeSaga } from "./sagas/resume-saga";
import type { DeviceInfo, GitCheckpointEvent } from "./types";
import { Logger } from "./utils/logger";

export interface ResumeState {
  conversation: ConversationTurn[];
  latestGitCheckpoint: GitCheckpointEvent | null;
  latestGitCheckpoints?: GitCheckpointEvent[];
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
  // Fold the log directly, ignoring any stored snapshot (used by the teardown
  // write path so it refreshes the snapshot instead of rewriting a stale one).
  skipSnapshot?: boolean;
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
    skipSnapshot: config.skipSnapshot,
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
    latestGitCheckpoints: result.data.latestGitCheckpoints,
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

const MAX_CONTENT_DATA_CHARS = 10_000;

// An image/audio payload (base64) or an embedded document rides in a content
// block's data/text field. selectRecentTurns never counts those bytes
// (estimateTurnTokens reads only top-level text) and formatConversationForResume
// never renders them (it keeps text blocks), so one attachment left whole can push
// the stored snapshot past its size limit and skip it entirely. Replace an oversized
// payload with a marker; the resume prompt reads only text blocks, so nothing it
// shows is lost.
function capContentBlock(block: ContentBlock): ContentBlock {
  if (block.type === "image" || block.type === "audio") {
    return block.data.length > MAX_CONTENT_DATA_CHARS
      ? { ...block, data: `[truncated ${block.data.length} chars]` }
      : block;
  }
  if (block.type === "resource") {
    const resource = block.resource;
    if ("text" in resource && resource.text.length > MAX_CONTENT_DATA_CHARS) {
      return {
        ...block,
        resource: {
          ...resource,
          text: `[truncated ${resource.text.length} chars]`,
        },
      };
    }
    if ("blob" in resource && resource.blob.length > MAX_CONTENT_DATA_CHARS) {
      return {
        ...block,
        resource: {
          ...resource,
          blob: `[truncated ${resource.blob.length} chars]`,
        },
      };
    }
  }
  return block;
}

/**
 * Reduce a rebuilt conversation to what a resume actually reads back.
 * The fold keeps tool payloads and attachment data whole, which runs a long task's
 * snapshot past the stored size limit, while the prompt below only renders a recent
 * window of text. Capping tool payloads and content-block data first keeps one
 * oversized turn from starving the window selection or overflowing the byte cap.
 * Dropping the synthetic resume preamble first matches formatConversationForResume:
 * that turn embeds the prior conversation summary, so leaving it in lets one giant
 * turn consume the budget and shed the real user turns the resume prompt needs.
 */
export function trimConversationForSnapshot(
  conversation: ConversationTurn[],
): ConversationTurn[] {
  const filtered = conversation.filter((turn) => !isResumeContextTurn(turn));
  const capped = filtered.map((turn) => ({
    ...turn,
    content: turn.content.map(capContentBlock),
    ...(turn.toolCalls?.length
      ? {
          toolCalls: turn.toolCalls.map((toolCall) => ({
            ...toolCall,
            input: capToolPayload(toolCall.input),
            ...(toolCall.result === undefined
              ? {}
              : { result: capToolPayload(toolCall.result) }),
          })),
        }
      : {}),
  }));
  return selectRecentTurns(capped, RESUME_HISTORY_TOKEN_BUDGET);
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
