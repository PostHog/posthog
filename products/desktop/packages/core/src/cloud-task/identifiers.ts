export const CLOUD_TASK_SERVICE = Symbol.for("posthog.core.cloudTaskService");
export const CLOUD_TASK_AUTH = Symbol.for("posthog.core.cloudTaskAuth");

export interface ICloudTaskAuth {
  authenticatedFetch(url: string, init?: RequestInit): Promise<Response>;
  getCloudContext(options?: { includeAccount?: boolean }): Promise<{
    apiHost: string;
    teamId: number;
    accountKey?: string | null;
  } | null>;
}

export interface ClaudeSubscriptionTokenStore {
  get(expectedAccountKey?: string): Promise<string | null>;
  save(token: string): Promise<void>;
  clear(): Promise<void>;
  clearAll(): Promise<void>;
  has(): Promise<boolean>;
}

export const CLAUDE_SUBSCRIPTION_TOKEN_STORE = Symbol.for(
  "posthog.cloud-task.claudeSubscriptionTokenStore",
);

export interface CodexSubscriptionTokens {
  accessToken: string;
  /** Codex rejects a `chatgptAuthTokens` login without this. */
  chatgptAccountId: string;
  chatgptPlanType?: string;
}

/**
 * Reads a live ChatGPT access token from the codex on this machine. Codex owns
 * the refresh token and rotates it, so nothing is stored here — `force` asks
 * codex to rotate before it answers, which is what a 401 in a sandbox needs.
 */
export interface CodexSubscriptionTokenSource {
  read(force?: boolean): Promise<CodexSubscriptionTokens | null>;
}

export const CODEX_SUBSCRIPTION_TOKEN_SOURCE = Symbol.for(
  "posthog.cloud-task.codexSubscriptionTokenSource",
);

/**
 * Host-bound executor for MCP relay requests (docs/CLOUD-MCP-RELAY.md).
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
