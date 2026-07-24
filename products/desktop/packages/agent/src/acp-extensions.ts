/**
 * PostHog-specific ACP extensions.
 *
 * These follow the ACP extensibility model:
 * - Custom notification methods are prefixed with `_posthog/`
 * - Custom data can be attached via `_meta` fields
 *
 * See: https://agentclientprotocol.com/docs/extensibility
 */

/**
 * Custom notification methods for PostHog-specific events.
 * Used with AgentSideConnection.extNotification() or Client.extNotification()
 */
export const POSTHOG_NOTIFICATIONS = {
  /** Git branch was created for a task */
  BRANCH_CREATED: "_posthog/branch_created",

  /** Task run has started execution */
  RUN_STARTED: "_posthog/run_started",

  /** Task has completed (success or failure) */
  TASK_COMPLETE: "_posthog/task_complete",

  /** Agent finished processing a turn (prompt returned, waiting for next input) */
  TURN_COMPLETE: "_posthog/turn_complete",

  /** Background/task-notification-triggered reply finished. Same rendering
   * effect as TURN_COMPLETE (closes out the current turn) without touching
   * the tracked prompt lifecycle that TURN_COMPLETE drives on the agent side. */
  BACKGROUND_TURN_COMPLETE: "_posthog/background_turn_complete",

  /** Error occurred during task execution */
  ERROR: "_posthog/error",

  /** Console/log output from the agent */
  CONSOLE: "_posthog/console",

  /** Maps taskRunId to agent's sessionId and adapter type (for resumption) */
  SDK_SESSION: "_posthog/sdk_session",

  /** Git checkpoint captured for handoff */
  GIT_CHECKPOINT: "_posthog/git_checkpoint",

  /** Agent mode changed (interactive/background) */
  MODE_CHANGE: "_posthog/mode_change",

  /** Request to resume a session from previous state */
  SESSION_RESUME: "_posthog/session/resume",

  /** User message sent from client to agent */
  USER_MESSAGE: "_posthog/user_message",

  /** Request to cancel current operation */
  CANCEL: "_posthog/cancel",

  /** Request to close the session */
  CLOSE: "_posthog/close",

  /** Agent status update (thinking, working, etc.) */
  STATUS: "_posthog/status",

  /** Structured backend progress notification; events in the same turn group into one card on the client */
  PROGRESS: "_posthog/progress",

  /** Task-level notification (progress, milestones) */
  TASK_NOTIFICATION: "_posthog/task_notification",

  /** Marks a boundary for log compaction */
  COMPACT_BOUNDARY: "_posthog/compact_boundary",

  /** Token usage update for a session turn */
  USAGE_UPDATE: "_posthog/usage_update",

  /** PostHog products used during a turn (derived from MCP exec calls) */
  RESOURCES_USED: "_posthog/resources_used",

  /** Response to a relayed permission request (plan approval, question) */
  PERMISSION_RESPONSE: "_posthog/permission_response",

  /** Permission request raised by the agent, persisted to the log so a reconnecting client can recover its requestId */
  PERMISSION_REQUEST: "_posthog/permission_request",

  /** Permission request resolved, persisted so a reconnecting client can tell it is no longer pending */
  PERMISSION_RESOLVED: "_posthog/permission_resolved",

  /** RTK output-compression token savings tallied at the end of a run */
  RTK_SAVINGS: "_posthog/rtk_savings",

  /** Latest native Codex goal state, persisted so cold cloud resumes can restore it. */
  CODEX_GOAL: "_posthog/codex_goal",
  /** Desktop → sandbox reply to an MCP relay request (docs/cloud-mcp-relay.md). */
  MCP_RESPONSE: "_posthog/mcp_response",
} as const;

export type NativeGoalState = {
  objective: string;
  status:
    | "active"
    | "paused"
    | "blocked"
    | "usageLimited"
    | "budgetLimited"
    | "complete";
};

/**
 * Custom request methods for PostHog-specific operations that need a response
 * (request/response, not fire-and-forget). Used with
 * ClientSideConnection.extMethod() on the sender and Agent.extMethod() on the
 * receiver.
 */
export const POSTHOG_METHODS = {
  /**
   * Client requests a session refresh between turns. Payload may include
   * `mcpServers` to trigger a resume-with-new-options reinit; future fields
   * can extend this without adding new methods. Returns once the refresh has
   * completed so the caller can safely send the next prompt.
   */
  REFRESH_SESSION: "_posthog/refresh_session",
} as const;

type PosthogNotification =
  (typeof POSTHOG_NOTIFICATIONS)[keyof typeof POSTHOG_NOTIFICATIONS];

type PosthogMethod = (typeof POSTHOG_METHODS)[keyof typeof POSTHOG_METHODS];

/**
 * Does `method` match `expected`? Shared by notification and method matchers.
 * Handles the `__posthog/` double-prefix that extNotification() can produce.
 */
function matchesExt(method: string | undefined, expected: string): boolean {
  if (!method) return false;
  return method === expected || method === `_${expected}`;
}

/** Dispatcher check for incoming `extNotification` calls on the agent side. */
export function isNotification(
  method: string | undefined,
  expected: PosthogNotification,
): boolean {
  return matchesExt(method, expected);
}

/** Dispatcher check for incoming `extMethod` calls on the agent side. */
export function isMethod(
  method: string | undefined,
  expected: PosthogMethod,
): boolean {
  return matchesExt(method, expected);
}
