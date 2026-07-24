/**
 * JSON-RPC message types for ACP protocol communication.
 * These types are used in both main process (session-manager.ts)
 * and renderer process (features/sessions) for message parsing.
 */

export interface JsonRpcNotification<T = unknown> {
  jsonrpc?: "2.0";
  method: string;
  params?: T;
}

export interface JsonRpcRequest<T = unknown> {
  jsonrpc?: "2.0";
  id: number;
  method: string;
  params?: T;
}

export interface JsonRpcResponse<T = unknown> {
  jsonrpc?: "2.0";
  id: number;
  result?: T;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

export type JsonRpcMessage =
  | JsonRpcNotification
  | JsonRpcRequest
  | JsonRpcResponse;

/**
 * Type guards for JSON-RPC messages
 */
export function isJsonRpcNotification(
  msg: JsonRpcMessage,
): msg is JsonRpcNotification {
  return "method" in msg && !("id" in msg);
}

export function isJsonRpcRequest(msg: JsonRpcMessage): msg is JsonRpcRequest {
  return "method" in msg && "id" in msg;
}

export function isJsonRpcResponse(msg: JsonRpcMessage): msg is JsonRpcResponse {
  return !("method" in msg) && "id" in msg;
}

/**
 * ACP message event emitted from main process to renderer.
 * This is the unified event type for all ACP protocol communication.
 *
 * The message source (client/agent) is inferred from the ACP protocol:
 * - user_message_chunk = user input
 * - agent_message_chunk, agent_thought_chunk, tool_call, etc = agent output
 */
export interface AcpMessage {
  type: "acp_message";
  ts: number;
  message: JsonRpcMessage;
}

/** Marks a replayed `user_message_chunk` from an imported transcript so the load path promotes it into a user bubble. */
export const IMPORTED_USER_PROMPT_META_KEY = "importedUserPrompt";

/**
 * S3 log entry format for stored session logs.
 * Used when fetching historical logs and appending new entries.
 */
export interface StoredLogEntry {
  type: string;
  timestamp?: string;
  notification?: {
    id?: number;
    method?: string;
    params?: unknown;
    result?: unknown;
    error?: unknown;
  };
}

export interface UserShellExecuteResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Params for user shell execute ACP extension notification.
 * Used for bash mode where user runs shell commands directly.
 * When `result` is undefined, the command is still in progress.
 */
export interface UserShellExecuteParams {
  id: string;
  command: string;
  cwd: string;
  result?: UserShellExecuteResult;
}
