import type { ContentBlock } from "@agentclientprotocol/sdk";
import { Saga } from "@posthog/shared";
import {
  isNotification,
  type NativeGoalState,
  POSTHOG_NOTIFICATIONS,
} from "../acp-extensions";
import type { PostHogAPIClient } from "../posthog-api";
import type { StoredNotification } from "../types";
import type { Logger } from "../utils/logger";
import { stripMcpResultMeta } from "../utils/mcp-result";

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

/** One tool call event's fields, before they are merged into a {@link ToolCallInfo}. */
interface PartialToolCall {
  toolCallId: string;
  toolName?: string;
  input?: unknown;
  result?: unknown;
}

export interface ResumeInput {
  taskId: string;
  runId: string;
  repositoryPath?: string;
  apiClient: PostHogAPIClient;
  logger?: Logger;
}

export interface ResumeOutput {
  conversation: ConversationTurn[];
  interrupted: boolean;
  logEntryCount: number;
  sessionId: string | null;
  nativeGoal?: NativeGoalState | null;
}

export class ResumeSaga extends Saga<ResumeInput, ResumeOutput> {
  readonly sagaName = "ResumeSaga";

  protected async execute(input: ResumeInput): Promise<ResumeOutput> {
    const { taskId, runId, apiClient } = input;

    // Step 1: Fetch task run (read-only)
    const taskRun = await this.readOnlyStep("fetch_task_run", () =>
      apiClient.getTaskRun(taskId, runId),
    );

    if (!taskRun.log_url) {
      this.log.info("No log URL found, starting fresh");
      return this.emptyResult();
    }

    // Step 2: Fetch log entries (read-only)
    const entries = await this.readOnlyStep("fetch_logs", () =>
      apiClient.fetchTaskRunLogs(taskRun),
    );

    if (entries.length === 0) {
      this.log.info("No log entries found, starting fresh");
      return this.emptyResult();
    }

    this.log.info("Fetched log entries", { count: entries.length });

    const conversation = await this.readOnlyStep("rebuild_conversation", () =>
      Promise.resolve(this.rebuildConversation(entries)),
    );

    const sessionId = await this.readOnlyStep("find_session_id", () =>
      Promise.resolve(this.findSessionId(entries)),
    );
    const nativeGoal = await this.readOnlyStep("find_native_goal", () =>
      Promise.resolve(this.findNativeGoal(entries)),
    );

    this.log.info("Resume state rebuilt", {
      turns: conversation.length,
      hasSessionId: !!sessionId,
      interrupted: false,
    });

    return {
      conversation,
      interrupted: false,
      logEntryCount: entries.length,
      sessionId,
      nativeGoal,
    };
  }

  private emptyResult(): ResumeOutput {
    return {
      conversation: [],
      interrupted: false,
      logEntryCount: 0,
      sessionId: null,
      nativeGoal: undefined,
    };
  }

  private findNativeGoal(
    entries: StoredNotification[],
  ): NativeGoalState | null | undefined {
    const statuses = new Set<NativeGoalState["status"]>([
      "active",
      "paused",
      "blocked",
      "usageLimited",
      "budgetLimited",
      "complete",
    ]);
    const methods = new Set([
      POSTHOG_NOTIFICATIONS.CODEX_GOAL,
      `_${POSTHOG_NOTIFICATIONS.CODEX_GOAL}`,
    ]);
    for (let index = entries.length - 1; index >= 0; index--) {
      const notification = entries[index].notification;
      if (!methods.has(notification?.method ?? "")) continue;
      const goal = (notification?.params as { goal?: unknown } | undefined)
        ?.goal;
      if (goal === null) return null;
      if (!goal || typeof goal !== "object") continue;
      const value = goal as Record<string, unknown>;
      if (
        typeof value.objective === "string" &&
        typeof value.status === "string" &&
        statuses.has(value.status as NativeGoalState["status"])
      ) {
        return {
          objective: value.objective,
          status: value.status as NativeGoalState["status"],
        };
      }
    }
    return undefined;
  }

  private findSessionId(entries: StoredNotification[]): string | null {
    // RUN_STARTED carries the session id the run booted with; a later
    // CONVERSATION_CLEARED (/clear) supersedes it with the fresh SDK session
    // id it swapped in. Latest entry of either kind wins outright — including
    // when it names no session: a /clear recorded without a sandbox (the
    // backend writes the marker straight to the log for a finished run) has no
    // session to continue, and scanning past it would find an earlier
    // RUN_STARTED and resume the very conversation the marker retired.
    for (let i = entries.length - 1; i >= 0; i--) {
      const method = entries[i].notification?.method;
      if (
        isNotification(method, POSTHOG_NOTIFICATIONS.RUN_STARTED) ||
        isNotification(method, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED)
      ) {
        const params = entries[i].notification?.params as
          | { sessionId?: string }
          | undefined;
        return typeof params?.sessionId === "string" && params.sessionId
          ? params.sessionId
          : null;
      }
    }
    return null;
  }

  private rebuildConversation(
    entries: StoredNotification[],
  ): ConversationTurn[] {
    let turns: ConversationTurn[] = [];
    let currentAssistantContent: ContentBlock[] = [];
    let currentToolCalls: ToolCallInfo[] = [];

    for (const entry of entries) {
      const method = entry.notification?.method;
      const params = entry.notification?.params as Record<string, unknown>;

      // /clear starts an empty conversation: everything before the marker is
      // gone from the model's context and must not be rehydrated.
      if (isNotification(method, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED)) {
        turns = [];
        currentAssistantContent = [];
        currentToolCalls = [];
        continue;
      }

      if (method === "session/update" && params?.update) {
        const update = params.update as Record<string, unknown>;
        const sessionUpdate = update.sessionUpdate as string;

        switch (sessionUpdate) {
          case "user_message":
          case "user_message_chunk": {
            if (
              currentAssistantContent.length > 0 ||
              currentToolCalls.length > 0
            ) {
              turns.push({
                role: "assistant",
                content: currentAssistantContent,
                toolCalls:
                  currentToolCalls.length > 0 ? currentToolCalls : undefined,
              });
              currentAssistantContent = [];
              currentToolCalls = [];
            }

            const content = update.content as ContentBlock | ContentBlock[];
            const contentArray = Array.isArray(content) ? content : [content];
            turns.push({
              role: "user",
              content: contentArray,
            });
            break;
          }

          case "agent_message": {
            const content = update.content as ContentBlock | undefined;
            if (content) {
              if (
                content.type === "text" &&
                currentAssistantContent.length > 0 &&
                currentAssistantContent[currentAssistantContent.length - 1]
                  .type === "text"
              ) {
                const lastBlock = currentAssistantContent[
                  currentAssistantContent.length - 1
                ] as { type: "text"; text: string };
                lastBlock.text += (
                  content as { type: "text"; text: string }
                ).text;
              } else {
                currentAssistantContent.push(content);
              }
            }
            break;
          }

          case "agent_message_chunk": {
            // Backward compatibility with older logs that have individual chunks
            const content = update.content as ContentBlock | undefined;
            if (content) {
              if (
                content.type === "text" &&
                currentAssistantContent.length > 0 &&
                currentAssistantContent[currentAssistantContent.length - 1]
                  .type === "text"
              ) {
                const lastBlock = currentAssistantContent[
                  currentAssistantContent.length - 1
                ] as { type: "text"; text: string };
                lastBlock.text += (
                  content as { type: "text"; text: string }
                ).text;
              } else {
                currentAssistantContent.push(content);
              }
            }
            break;
          }

          case "tool_call":
          case "tool_call_update":
          case "tool_result": {
            mergeToolCall(currentToolCalls, readToolCall(update));
            break;
          }
        }
      }
    }

    if (currentAssistantContent.length > 0 || currentToolCalls.length > 0) {
      turns.push({
        role: "assistant",
        content: currentAssistantContent,
        toolCalls: currentToolCalls.length > 0 ? currentToolCalls : undefined,
      });
    }

    return turns;
  }
}

/**
 * Fold one tool call event into the turn's calls. A call is created on the
 * first event that names it, and later events fill in what they carry, so a
 * result that arrives on a separate update still reaches the resume prompt.
 */
function mergeToolCall(
  toolCalls: ToolCallInfo[],
  fields: PartialToolCall,
): void {
  if (!fields.toolCallId) return;
  let toolCall = toolCalls.find((tc) => tc.toolCallId === fields.toolCallId);
  if (!toolCall) {
    if (!fields.toolName) return;
    toolCall = {
      toolCallId: fields.toolCallId,
      toolName: fields.toolName,
      input: fields.input,
    };
    toolCalls.push(toolCall);
  } else if (
    fields.input !== undefined &&
    (toolCall.input === undefined || !isEmptyRecord(fields.input))
  ) {
    // The opening tool_call ships `rawInput: {}`, so a later cumulative
    // snapshot has to win — but an empty one must not clobber a stored input.
    toolCall.input = fields.input;
  }
  if (fields.result !== undefined) {
    toolCall.result = fields.result;
  }
}

function isEmptyRecord(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).length === 0
  );
}

/**
 * Tool call fields, read from wherever the emitting runtime puts them. ACP
 * carries the id and the payloads on the update itself, and every adapter
 * emits them there; `_meta.claudeCode` only reliably carries `toolName` (and
 * sometimes `toolResponse`), so it is a per-field fallback for older logs
 * rather than an alternative source. Codex and pi name their calls on
 * `_meta.posthog`, and a plain shell call carries no meta at all, leaving
 * `title` as the only name.
 */
function readToolCall(update: Record<string, unknown>): PartialToolCall {
  const meta = update._meta as Record<string, unknown> | undefined;
  const claudeMeta = meta?.claudeCode as Record<string, unknown> | undefined;
  const posthogMeta = meta?.posthog as Record<string, unknown> | undefined;

  let result = firstDefined(update.rawOutput, claudeMeta?.toolResponse);
  if (result === undefined) result = toolContentText(update.content);

  return {
    toolCallId: firstString(update.toolCallId, claudeMeta?.toolCallId) ?? "",
    toolName: firstString(
      claudeMeta?.toolName,
      posthogMeta?.toolName,
      update.title,
    ),
    input: firstDefined(update.rawInput, claudeMeta?.toolInput),
    result: stripMcpResultMeta(result),
  };
}

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === "string");
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined);
}

/** The text of an ACP tool call's content blocks, for a call with no `rawOutput`. */
function toolContentText(content: unknown): string | undefined {
  if (!Array.isArray(content)) return undefined;
  const texts: string[] = [];
  for (const block of content) {
    const inner = (block as { content?: unknown } | null)?.content as
      | { type?: unknown; text?: unknown }
      | undefined;
    if (inner?.type === "text" && typeof inner.text === "string") {
      texts.push(inner.text);
    }
  }
  return texts.length > 0 ? texts.join("\n") : undefined;
}
