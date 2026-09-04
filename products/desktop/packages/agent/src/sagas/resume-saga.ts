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
          case "tool_call_update": {
            const meta = (update._meta as Record<string, unknown>)
              ?.claudeCode as Record<string, unknown> | undefined;
            if (meta) {
              const toolCallId = meta.toolCallId as string | undefined;
              const toolName = meta.toolName as string | undefined;
              const toolInput = meta.toolInput;
              const toolResponse = meta.toolResponse;

              if (toolCallId && toolName) {
                let toolCall = currentToolCalls.find(
                  (tc) => tc.toolCallId === toolCallId,
                );
                if (!toolCall) {
                  toolCall = {
                    toolCallId,
                    toolName,
                    input: toolInput,
                  };
                  currentToolCalls.push(toolCall);
                }

                if (toolResponse !== undefined) {
                  toolCall.result = toolResponse;
                }
              }
            }
            break;
          }

          case "tool_result": {
            const meta = (update._meta as Record<string, unknown>)
              ?.claudeCode as Record<string, unknown> | undefined;
            if (meta) {
              const toolCallId = meta.toolCallId as string | undefined;
              const toolResponse = meta.toolResponse;

              if (toolCallId) {
                const toolCall = currentToolCalls.find(
                  (tc) => tc.toolCallId === toolCallId,
                );
                if (toolCall && toolResponse !== undefined) {
                  toolCall.result = toolResponse;
                }
              }
            }
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
