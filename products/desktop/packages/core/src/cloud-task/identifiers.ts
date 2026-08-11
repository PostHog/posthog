export const CLOUD_TASK_SERVICE = Symbol.for("posthog.core.cloudTaskService");
export const CLOUD_TASK_AUTH = Symbol.for("posthog.core.cloudTaskAuth");

export interface ICloudTaskAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
  getCloudContext(): Promise<{ apiHost: string; teamId: number } | null>;
}

/**
 * Host-bound executor for MCP relay requests (docs/cloud-mcp-relay.md).
 * Desktop binds this to the workspace-server relay service; hosts without a
 * local workspace leave it unbound and relay events are ignored.
 */
export const MCP_RELAY_EXECUTOR = Symbol.for("posthog.core.mcpRelayExecutor");

export interface McpRelayExecution {
  payload?: Record<string, unknown>;
  error?: { code: number; message: string };
}

export interface McpRelayExecutor {
  execute(
    runId: string,
    server: string,
    payload: Record<string, unknown>,
  ): Promise<McpRelayExecution>;
  /** Release the run's live server connections; they reopen lazily on demand. */
  closeRun?(runId: string): Promise<void>;
}
