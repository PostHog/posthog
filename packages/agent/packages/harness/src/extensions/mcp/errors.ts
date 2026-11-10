/**
 * Single error class for all MCP-related failures.
 *
 * The `code` field enables programmatic discrimination without an
 * instanceof hierarchy.
 */

export type McpErrorCode =
  /** Configuration loading or validation failed. */
  | "config"
  /** Transport/connection failed. */
  | "connection"
  /** JSON-RPC protocol violation (server error response, timeout, ...). */
  | "protocol"
  /** Tool execution error (`isError: true` from the server). */
  | "tool";

export class McpError extends Error {
  readonly server: string;
  readonly code: McpErrorCode;

  constructor(
    message: string,
    server: string,
    code: McpErrorCode,
    cause?: unknown,
  ) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "McpError";
    this.server = server;
    this.code = code;
  }

  /** Short user-facing message suitable for `ctx.ui.notify()`. */
  get userMessage(): string {
    return `[${this.server}] ${this.message}`;
  }
}

/** Normalize an unknown thrown value into a user-facing message. */
export function describeError(err: unknown): string {
  if (err instanceof McpError) return err.userMessage;
  if (err instanceof Error) return err.message;
  return String(err);
}
