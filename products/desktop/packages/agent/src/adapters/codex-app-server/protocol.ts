/**
 * Minimal typings for the native Codex `app-server` JSON-RPC protocol
 * (https://developers.openai.com/codex/app-server). Wire framing is
 * newline-delimited JSON that omits the `"jsonrpc": "2.0"` header.
 */

export const APP_SERVER_METHODS = {
  INITIALIZE: "initialize",
  THREAD_START: "thread/start",
  THREAD_RESUME: "thread/resume",
  THREAD_FORK: "thread/fork",
  TURN_START: "turn/start",
  // Inject input into the active turn (mirrors Claude's mid-turn steering); fails unless `expectedTurnId` matches.
  TURN_STEER: "turn/steer",
  TURN_INTERRUPT: "turn/interrupt",
  MODEL_LIST: "model/list",
  SKILLS_LIST: "skills/list",
  THREAD_GOAL_SET: "thread/goal/set",
  THREAD_GOAL_GET: "thread/goal/get",
  THREAD_GOAL_CLEAR: "thread/goal/clear",
  THREAD_LIST: "thread/list",
} as const;

export const APP_SERVER_NOTIFICATIONS = {
  INITIALIZED: "initialized",
  THREAD_STARTED: "thread/started",
  // Carries the active turn id — precondition for turn/steer + turn/interrupt.
  TURN_STARTED: "turn/started",
  ITEM_STARTED: "item/started",
  ITEM_COMPLETED: "item/completed",
  AGENT_MESSAGE_DELTA: "item/agentMessage/delta",
  REASONING_TEXT_DELTA: "item/reasoning/textDelta",
  // Default reasoning stream for gpt-5 models; raw textDelta is off by default, so without this the host sees no reasoning.
  REASONING_SUMMARY_TEXT_DELTA: "item/reasoning/summaryTextDelta",
  // Plan-mode <proposed_plan> stream. The adapter buffers it for the structured
  // plan approval UI because codex strips it from agentMessage deltas.
  PLAN_DELTA: "item/plan/delta",
  TURN_PLAN_UPDATED: "turn/plan/updated",
  TURN_COMPLETED: "turn/completed",
  // Fatal turn error; `willRetry:false` means it won't recover on its own.
  ERROR: "error",
  TOKEN_USAGE_UPDATED: "thread/tokenUsage/updated",
  // codex auto-compacted the thread; mirrors Claude's compact_boundary so the host's context indicator + queue drain fire.
  CONTEXT_COMPACTED: "thread/compacted",
  COMMAND_OUTPUT_DELTA: "item/commandExecution/outputDelta",
  // Per-server MCP startup progress. `status: "failed"` is the only signal codex
  // emits when a configured server dies at launch — its tools silently never appear.
  MCP_STARTUP_STATUS: "mcpServer/startupStatus/updated",
  // PTY-level stdin echoed back for an interactive terminal command.
  TERMINAL_INTERACTION: "item/commandExecution/terminalInteraction",
  FILE_CHANGE_PATCH_UPDATED: "item/fileChange/patchUpdated",
} as const;

/**
 * Server-initiated requests the client must answer. The two approvals are yes/no
 * decisions; the richer requests carry distinct response shapes (multi-question
 * prompt, permission-profile grant, MCP elicitation).
 */
export const APP_SERVER_REQUESTS = {
  COMMAND_APPROVAL: "item/commandExecution/requestApproval",
  FILE_CHANGE_APPROVAL: "item/fileChange/requestApproval",
  TOOL_USER_INPUT: "item/tool/requestUserInput",
  PERMISSIONS_APPROVAL: "item/permissions/requestApproval",
  MCP_ELICITATION: "mcpServer/elicitation/request",
} as const;

/** JSON-RPC ids are `string | number` per the codex schema (`RequestId.ts`). */
export type RequestId = string | number;

export interface JsonRpcRequest {
  id: RequestId;
  method: string;
  params?: unknown;
}

export interface JsonRpcNotification {
  method: string;
  params?: unknown;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface JsonRpcResponse {
  id: RequestId;
  result?: unknown;
  error?: JsonRpcError;
}

export type JsonRpcMessage =
  | JsonRpcRequest
  | JsonRpcNotification
  | JsonRpcResponse;
