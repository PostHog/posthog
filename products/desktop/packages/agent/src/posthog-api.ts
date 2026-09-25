import {
  API_DOWNLOAD_TIMEOUT_MS,
  API_TRANSFER_TIMEOUT_MS,
  type McpServerConnection,
  type McpToolApprovalState,
  type McpToolPolicy,
  PostHogHttpClient,
  type StoredLogEntry,
  type TaskRunUpdate,
  taskRunStateSchema,
} from "@posthog/shared";
import packageJson from "../package.json" with { type: "json" };
import type { PostHogAPIConfig, StoredEntry, Task, TaskRun } from "./types";
import { getGatewayUsageUrl, getLlmGatewayUrl } from "./utils/gateway";

export { getGatewayUsageUrl, getLlmGatewayUrl };
export { API_TRANSFER_TIMEOUT_MS, type TaskRunUpdate };

const DEFAULT_USER_AGENT = `posthog/agent.hog.dev; version: ${packageJson.version}`;

export interface TaskSessionStorageAccess {
  id: string;
  download_url: string | null;
  content_sha256: string | null;
}

export interface CodexSubscriptionAccessGrant {
  access_token: string;
  account_id: string;
  plan_type: string | null;
  expires_at: string;
}

export type CodexSubscriptionTokenErrorCode =
  | "reauth_required"
  | "openai_unavailable"
  | "forbidden"
  | "request_failed";

export class CodexSubscriptionTokenError extends Error {
  constructor(
    readonly code: CodexSubscriptionTokenErrorCode,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "CodexSubscriptionTokenError";
  }
}

export type ClaudeSubscriptionTokenErrorCode =
  | "reauth_required"
  | "forbidden"
  | "request_failed";

export class ClaudeSubscriptionTokenError extends Error {
  constructor(
    readonly code: ClaudeSubscriptionTokenErrorCode,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ClaudeSubscriptionTokenError";
  }
}

export class PostHogAPIError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly credentialsRefreshable: boolean = false,
  ) {
    super(message);
    this.name = "PostHogAPIError";
  }

  get retryable(): boolean {
    if (this.status === 401) {
      return this.credentialsRefreshable;
    }
    return this.status >= 500 || this.status === 408 || this.status === 429;
  }
}

export class PostHogAPIClient {
  private readonly http: PostHogHttpClient;
  private userNode: string | null | undefined;

  constructor(readonly config: PostHogAPIConfig) {
    this.http = new PostHogHttpClient(config, {
      defaultUserAgent: DEFAULT_USER_AGENT,
      buildError: (message, status) =>
        new PostHogAPIError(message, status, Boolean(config.refreshApiKey)),
    });
  }

  private get baseUrl(): string {
    return this.http.baseUrl;
  }

  private getTeamId(): number {
    return this.http.getTeamId();
  }

  private apiRequest<T>(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<T> {
    return this.http.request<T>(endpoint, options);
  }

  private performRequestWithRetry(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<Response> {
    return this.http.performRequestWithRetry(endpoint, options);
  }

  async getApiKey(forceRefresh = false): Promise<string> {
    return this.http.resolveApiKey(forceRefresh);
  }

  getLlmGatewayUrl(): string {
    return getLlmGatewayUrl(this.baseUrl);
  }

  /**
   * The gateway user node for the signed-in person, or null when the credential
   * resolves to no user (a task-scoped token). This is the distinct id, not the
   * uuid: it has to match what a per-person spend limit is keyed on and what a
   * cloud run pins into its token, so the `user_{id}` fallback mirrors
   * products/ai_gateway/backend/logic.py (_spend_node) exactly — diverging from it writes a
   * budget nothing debits. Successful lookups are cached, since the node never
   * changes for a credential; a failed lookup is not, so a startup network blip
   * doesn't permanently disable the spend-limit header.
   */
  async getUserNode(): Promise<string | null> {
    if (this.userNode !== undefined) return this.userNode;
    try {
      const user = await this.apiRequest<{
        id?: number;
        distinct_id?: string;
      }>("/api/users/@me/", {
        // Best-effort header on session start: bound the request so a stalled
        // socket can't hold up the run. The catch below then returns null.
        signal: AbortSignal.timeout(API_TRANSFER_TIMEOUT_MS),
      });
      this.userNode =
        user.distinct_id || (user.id != null ? `user_${user.id}` : null);
    } catch {
      return null;
    }
    return this.userNode;
  }

  async getTask(taskId: string): Promise<Task> {
    const teamId = this.getTeamId();
    return this.apiRequest<Task>(`/api/projects/${teamId}/tasks/${taskId}/`);
  }

  async getMcpRuntimeConfiguration(
    servers: McpServerConnection[],
  ): Promise<{ servers: McpServerConnection[]; policies: McpToolPolicy[] }> {
    const resolved = await Promise.all(
      servers.map(async (server) => {
        const installationId = this.mcpInstallationId(server.url);
        if (!installationId) {
          return { server, policies: [] };
        }

        try {
          const response = await this.apiRequest<{
            results?: Array<{
              tool_name: string;
              approval_state?: McpToolApprovalState;
              description?: string;
            }>;
          }>(
            `/api/environments/${this.getTeamId()}/mcp_server_installations/${installationId}/tools/`,
          );
          const policies = (response.results ?? []).flatMap((tool) =>
            tool.approval_state
              ? [
                  {
                    serverName: server.name,
                    toolName: tool.tool_name,
                    installationId,
                    approvalState: tool.approval_state,
                    ...(tool.description
                      ? { description: tool.description }
                      : {}),
                  } satisfies McpToolPolicy,
                ]
              : [],
          );
          return { server, policies };
        } catch {
          return null;
        }
      }),
    );

    return {
      servers: resolved.flatMap((entry) => (entry ? [entry.server] : [])),
      policies: resolved.flatMap((entry) => entry?.policies ?? []),
    };
  }

  async approveMcpTool(
    installationId: string,
    toolName: string,
  ): Promise<void> {
    await this.apiRequest(
      `/api/environments/${this.getTeamId()}/mcp_server_installations/${installationId}/tools/${encodeURIComponent(toolName)}/`,
      {
        method: "PATCH",
        body: JSON.stringify({ approval_state: "approved" }),
      },
    );
  }

  private mcpInstallationId(url: string): string | null {
    try {
      const serverUrl = new URL(url);
      if (serverUrl.origin !== new URL(this.baseUrl).origin) {
        return null;
      }
      const match = serverUrl.pathname.match(
        /\/mcp_server_installations\/([^/]+)\/proxy\/?$/,
      );
      return match?.[1] ? decodeURIComponent(match[1]) : null;
    } catch {
      return null;
    }
  }

  async getTaskRun(
    taskId: string,
    runId: string,
    signal?: AbortSignal,
  ): Promise<TaskRun> {
    const teamId = this.getTeamId();
    const taskRun = await this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
      { signal },
    );
    return { ...taskRun, state: taskRunStateSchema.parse(taskRun.state) };
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    payload: TaskRunUpdate,
    signal?: AbortSignal,
  ): Promise<TaskRun> {
    return this.http.updateTaskRun(taskId, runId, payload, signal);
  }

  async setTaskRunOutput(
    taskId: string,
    runId: string,
    output: Record<string, unknown>,
  ): Promise<TaskRun> {
    return this.apiRequest(
      `/api/projects/${this.getTeamId()}/tasks/${taskId}/runs/${runId}/set_output/`,
      {
        method: "PATCH",
        body: JSON.stringify(output),
      },
    );
  }

  async getTaskSession(
    taskId: string,
    runId: string,
  ): Promise<TaskSessionStorageAccess> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskSessionStorageAccess>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/task_session/`,
    );
  }

  async downloadTaskSession(access: TaskSessionStorageAccess): Promise<string> {
    if (!access.download_url) {
      return "";
    }
    const response = await fetch(access.download_url, {
      signal: AbortSignal.timeout(30_000),
    });
    if (response.status === 404) {
      return "";
    }
    if (!response.ok) {
      throw new Error(
        `Failed to download task session: [${response.status}] ${response.statusText}`,
      );
    }
    return response.text();
  }

  async syncTaskSession(
    taskId: string,
    runId: string,
    sandboxId: string,
    expectedContentSha256: string | null,
    content: string,
    taskRunToken: string,
  ): Promise<string> {
    const teamId = this.getTeamId();
    const response = await this.performRequestWithRetry(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/task_session_sync/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "If-Match": `"${expectedContentSha256 ?? "none"}"`,
          "X-Sandbox-ID": sandboxId,
          "X-Task-Run-Token": taskRunToken,
        },
        body: content,
        signal: AbortSignal.timeout(30_000),
      },
    );
    if (!response.ok) {
      const error = await response.text().catch(() => response.statusText);
      throw new Error(
        `Failed to sync task session: [${response.status}] ${error}`,
      );
    }
    const result = (await response.json()) as { content_sha256: string };
    return result.content_sha256;
  }

  /**
   * A short-lived ChatGPT access token for a run on the owner's own plan. The
   * run token from fd 3 proves the caller is this run's agent-server; the
   * refresh token never leaves the server. `force` asks for a new token even
   * when the stored one has not expired, for when Codex rejected the last one.
   */
  async requestCodexSubscriptionToken(
    taskId: string,
    runId: string,
    runToken: string,
    rejectedAccessTokenSha256: string | null,
    timeoutMs: number,
  ): Promise<CodexSubscriptionAccessGrant> {
    const teamId = this.getTeamId();
    const response = await this.performRequestWithRetry(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/subscription_token/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Task-Run-Token": runToken,
        },
        body: JSON.stringify({
          rejected_access_token_sha256: rejectedAccessTokenSha256,
        }),
        signal: AbortSignal.timeout(timeoutMs),
      },
    ).catch(() => {
      throw new CodexSubscriptionTokenError(
        "request_failed",
        0,
        "Could not reach PostHog to get a ChatGPT token. Try the task again.",
      );
    });
    if (response.ok) {
      return (await response.json()) as CodexSubscriptionAccessGrant;
    }
    const body = (await response.json().catch(() => ({}))) as {
      code?: string;
      error?: string;
    };
    const code: CodexSubscriptionTokenErrorCode =
      body.code === "reauth_required" || body.code === "openai_unavailable"
        ? body.code
        : response.status === 403 || response.status === 404
          ? "forbidden"
          : "request_failed";
    throw new CodexSubscriptionTokenError(
      code,
      response.status,
      `Failed to get a ChatGPT token: [${response.status}] ${body.error ?? response.statusText}`,
    );
  }

  async requestClaudeSubscriptionToken(
    taskId: string,
    runId: string,
    runToken: string,
    rejectedTokenSha256: string | null,
    timeoutMs: number,
  ): Promise<string> {
    const teamId = this.getTeamId();
    const response = await this.performRequestWithRetry(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/claude_subscription_token/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Task-Run-Token": runToken,
        },
        body: JSON.stringify({ rejected_token_sha256: rejectedTokenSha256 }),
        signal: AbortSignal.timeout(timeoutMs),
      },
    ).catch(() => {
      throw new ClaudeSubscriptionTokenError(
        "request_failed",
        0,
        "Could not reach PostHog to get the Claude token. Try the task again.",
      );
    });
    if (response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        token?: unknown;
      };
      if (typeof body.token === "string" && body.token) return body.token;
      throw new ClaudeSubscriptionTokenError(
        "request_failed",
        response.status,
        "PostHog did not return a Claude token.",
      );
    }
    const body = (await response.json().catch(() => ({}))) as {
      code?: string;
      error?: string;
    };
    const code: ClaudeSubscriptionTokenErrorCode =
      body.code === "reauth_required"
        ? "reauth_required"
        : response.status === 403 || response.status === 404
          ? "forbidden"
          : "request_failed";
    throw new ClaudeSubscriptionTokenError(
      code,
      response.status,
      `Failed to get the Claude token: [${response.status}] ${body.error ?? response.statusText}`,
    );
  }

  async appendTaskRunLog(
    taskId: string,
    runId: string,
    entries: (StoredEntry | StoredLogEntry)[],
  ): Promise<TaskRun> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/append_log/`,
      {
        method: "POST",
        body: JSON.stringify({ entries }),
      },
    );
  }

  async relayMessage(
    taskId: string,
    runId: string,
    text: string,
    textParts?: string[],
    messageId?: string,
    traceId?: string | null,
  ): Promise<void> {
    const teamId = this.getTeamId();
    // Send `text_parts` alongside the joined `text` so backends that understand
    // the new schema can pick just the post-last-tool-use answer, while older
    // backends still get the flat `text` field they already handle.
    // `message_id` correlates the relay with the user message that initiated
    // the turn; it is omitted when no message id is known (e.g. boot prompt).
    const body: {
      text: string;
      text_parts?: string[];
      message_id?: string;
      trace_id?: string;
    } = {
      text,
    };
    if (textParts && textParts.length > 0) {
      body.text_parts = textParts;
    }
    if (messageId) {
      body.message_id = messageId;
    }
    if (traceId) {
      body.trace_id = traceId;
    }
    await this.apiRequest<{ status: string }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/relay_message/`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  }

  /**
   * Download artifact content by storage path
   * Streams the file through the PostHog backend so the sandbox does not need
   * direct access to object storage.
   */
  async downloadArtifact(
    taskId: string,
    runId: string,
    storagePath: string,
  ): Promise<ArrayBuffer | null> {
    const teamId = this.getTeamId();

    try {
      const response = await this.performRequestWithRetry(
        `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/download/`,
        {
          method: "POST",
          body: JSON.stringify({ storage_path: storagePath }),
          signal: AbortSignal.timeout(API_DOWNLOAD_TIMEOUT_MS),
        },
      );
      if (!response.ok) {
        throw new Error(`Failed to download artifact: ${response.status}`);
      }
      return response.arrayBuffer();
    } catch {
      return null;
    }
  }

  /**
   * Fetch logs for a task run via the logs API endpoint
   * @param taskRun - The task run to fetch logs for
   * @returns Array of stored entries, or empty array if no logs available
   */
  async fetchTaskRunLogs(taskRun: TaskRun): Promise<StoredEntry[]> {
    const teamId = this.getTeamId();
    const endpoint = `/api/projects/${teamId}/tasks/${taskRun.task}/runs/${taskRun.id}/logs`;

    try {
      const response = await this.performRequestWithRetry(endpoint, {
        signal: AbortSignal.timeout(API_DOWNLOAD_TIMEOUT_MS),
      });

      if (!response.ok) {
        if (response.status === 404) {
          return [];
        }
        throw new Error(
          `Failed to fetch logs: ${response.status} ${response.statusText}`,
        );
      }

      const content = await response.text();

      if (!content.trim()) {
        return [];
      }

      // Parse newline-delimited JSON
      return content
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as StoredEntry);
    } catch (error) {
      throw new Error(
        `Failed to fetch task run logs: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
}
