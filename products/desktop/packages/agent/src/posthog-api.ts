import {
  type McpServerConnection,
  type McpToolApprovalState,
  type McpToolPolicy,
  type StoredLogEntry,
  taskRunStateSchema,
} from "@posthog/shared";
import packageJson from "../package.json" with { type: "json" };
import type {
  ArtifactSource,
  ArtifactType,
  PostHogAPIConfig,
  StoredEntry,
  Task,
  TaskRun,
  TaskRunArtifact,
} from "./types";
import { getGatewayUsageUrl, getLlmGatewayUrl } from "./utils/gateway";

export { getGatewayUsageUrl, getLlmGatewayUrl };

const DEFAULT_USER_AGENT = `posthog/agent.hog.dev; version: ${packageJson.version}`;

// Deadlines for artifact transfers. Control-plane JSON gets the client's flat 30s
// convention (downloadTaskSession, syncTaskSession); byte-carrying payloads scale
// with size at a 256 KB/s throughput floor, so a slow-but-working link can finish
// a 30MB upload while a stall still aborts long before undici's ~5-minute
// internal defaults.
export const API_TRANSFER_TIMEOUT_MS = 30_000;
const MIN_TRANSFER_BYTES_PER_MS = 256;

export function transferTimeoutMs(byteLength: number): number {
  return Math.max(
    API_TRANSFER_TIMEOUT_MS,
    Math.ceil(byteLength / MIN_TRANSFER_BYTES_PER_MS),
  );
}

export interface TaskArtifactUploadPayload {
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  content: string;
  /** Encoding of `content`. With "base64" the backend stores the decoded bytes. */
  content_encoding?: "utf-8" | "base64";
  content_type?: string;
}

export interface TaskArtifactPrepareUploadPayload {
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  size: number;
  content_type?: string;
}

export interface PreparedTaskArtifactUpload {
  id: string;
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  size: number;
  content_type?: string;
  storage_path: string;
  expires_in: number;
  presigned_post: { url: string; fields: Record<string, string> };
}

export interface TaskSessionStorageAccess {
  id: string;
  download_url: string | null;
  content_sha256: string | null;
}

export interface TaskArtifactFinalizeUploadPayload {
  id: string;
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  storage_path: string;
  content_type?: string;
}

/** One peer agent run visible to a sender run (agent peer messaging discovery). */
export interface TaskRunPeer {
  run_id: string;
  task_id: string;
  task_title: string;
  created_by_email: string | null;
  runtime: string;
  model: string | null;
  repository: string | null;
  stage: string | null;
  status: string;
  /** Whether the peer accepts messages right now; never infer this from `status`. */
  sendable: boolean;
  updated_at: string | null;
}

export interface PeerMessageSendResult {
  /**
   * "accepted" (queued for delivery — not a delivery confirmation),
   * "target_finished" (the peer's workflow is gone), or "rejected".
   */
  result: string;
  detail: string;
  message_id?: string | null;
}

export type TaskRunUpdate = Partial<
  Pick<
    TaskRun,
    | "status"
    | "branch"
    | "stage"
    | "error_message"
    | "output"
    | "state"
    | "environment"
  >
> & {
  state_remove_keys?: string[];
  state_append?: Record<string, unknown>;
};

export class PostHogAPIClient {
  private config: PostHogAPIConfig;
  private userNode: string | null | undefined;

  constructor(config: PostHogAPIConfig) {
    this.config = config;
  }

  private get baseUrl(): string {
    const host = this.config.apiUrl.endsWith("/")
      ? this.config.apiUrl.slice(0, -1)
      : this.config.apiUrl;
    return host;
  }

  private isAuthFailure(status: number): boolean {
    return status === 401 || status === 403;
  }

  private async resolveApiKey(forceRefresh = false): Promise<string> {
    if (forceRefresh && this.config.refreshApiKey) {
      return this.config.refreshApiKey();
    }

    return this.config.getApiKey();
  }

  private async buildHeaders(
    options: RequestInit,
    forceRefresh = false,
  ): Promise<Headers> {
    const headers = new Headers(options.headers);
    headers.set(
      "Authorization",
      `Bearer ${await this.resolveApiKey(forceRefresh)}`,
    );
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    headers.set("User-Agent", this.config.userAgent ?? DEFAULT_USER_AGENT);
    return headers;
  }

  private async performRequest(
    endpoint: string,
    options: RequestInit,
    forceRefresh = false,
  ): Promise<Response> {
    const url = `${this.baseUrl}${endpoint}`;

    return fetch(url, {
      ...options,
      headers: await this.buildHeaders(options, forceRefresh),
    });
  }

  private async performRequestWithRetry(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<Response> {
    let response = await this.performRequest(endpoint, options);

    if (!response.ok && this.isAuthFailure(response.status)) {
      response = await this.performRequest(endpoint, options, true);
    }

    return response;
  }

  private async apiRequest<T>(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<T> {
    const response = await this.performRequestWithRetry(endpoint, options);

    if (!response.ok) {
      let errorMessage: string;
      try {
        const errorResponse = await response.json();
        errorMessage = `Failed request: [${response.status}] ${JSON.stringify(errorResponse)}`;
      } catch {
        errorMessage = `Failed request: [${response.status}] ${response.statusText}`;
      }
      throw new Error(errorMessage);
    }

    return response.json();
  }

  private getTeamId(): number {
    return this.config.projectId;
  }

  async getApiKey(forceRefresh = false): Promise<string> {
    return this.resolveApiKey(forceRefresh);
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

  /**
   * File one task-analysis finding. The server owns the findings list, validates the
   * shape and enforces the per-run cap, so this is the only way to add one.
   */
  async reportAnalysisInsight(
    taskId: string,
    runId: string,
    insight: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<{ insight_index: number }> {
    const teamId = this.getTeamId();
    return this.apiRequest<{ insight_index: number }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/analysis-insight/`,
      {
        method: "POST",
        body: JSON.stringify(insight),
        signal,
      },
    );
  }

  async resumeRunInCloud(taskId: string, runId: string): Promise<TaskRun> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/resume_in_cloud/`,
      { method: "POST" },
    );
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    payload: TaskRunUpdate,
    signal?: AbortSignal,
  ): Promise<TaskRun> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
        signal,
      },
    );
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
  ): Promise<void> {
    const teamId = this.getTeamId();
    // Send `text_parts` alongside the joined `text` so backends that understand
    // the new schema can pick just the post-last-tool-use answer, while older
    // backends still get the flat `text` field they already handle.
    // `message_id` correlates the relay with the user message that initiated
    // the turn; it is omitted when no message id is known (e.g. boot prompt).
    const body: { text: string; text_parts?: string[]; message_id?: string } = {
      text,
    };
    if (textParts && textParts.length > 0) {
      body.text_parts = textParts;
    }
    if (messageId) {
      body.message_id = messageId;
    }
    await this.apiRequest<{ status: string }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/relay_message/`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  }

  async uploadTaskArtifacts(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactUploadPayload[],
  ): Promise<TaskRunArtifact[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = this.getTeamId();
    const body = JSON.stringify({ artifacts });
    const response = await this.apiRequest<{ artifacts: TaskRunArtifact[] }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/`,
      {
        method: "POST",
        body,
        // Carries the (base64-inflated) artifact bytes, so the deadline scales
        // with the payload like the direct-to-storage POST does.
        signal: AbortSignal.timeout(transferTimeoutMs(body.length)),
      },
    );

    const manifest = response.artifacts ?? [];

    // The backend returns the full run artifact manifest after each upload.
    // Callers want the artifacts corresponding to this upload request only.
    return manifest.slice(-artifacts.length);
  }

  /**
   * Reserve S3 keys and presigned POST forms so artifact bytes can be
   * uploaded directly to object storage instead of traveling base64-encoded
   * through the API (which enforces much smaller request body limits).
   */
  async prepareTaskArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactPrepareUploadPayload[],
  ): Promise<PreparedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = this.getTeamId();
    const response = await this.apiRequest<{
      artifacts: PreparedTaskArtifactUpload[];
    }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/prepare_upload/`,
      {
        method: "POST",
        body: JSON.stringify({ artifacts }),
        signal: AbortSignal.timeout(API_TRANSFER_TIMEOUT_MS),
      },
    );
    return response.artifacts ?? [];
  }

  /** Attach directly-uploaded artifacts (see prepareTaskArtifactUploads) to the run manifest. */
  async finalizeTaskArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactFinalizeUploadPayload[],
  ): Promise<TaskRunArtifact[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = this.getTeamId();
    const response = await this.apiRequest<{ artifacts: TaskRunArtifact[] }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/finalize_upload/`,
      {
        method: "POST",
        body: JSON.stringify({ artifacts }),
        signal: AbortSignal.timeout(API_TRANSFER_TIMEOUT_MS),
      },
    );

    // The backend returns the full run artifact manifest; pick out the
    // entries for this request (retried finalizes can land mid-manifest).
    const manifest = response.artifacts ?? [];
    const byStoragePath = new Map(
      manifest.map((artifact) => [artifact.storage_path, artifact]),
    );
    return artifacts
      .map((artifact) => byStoragePath.get(artifact.storage_path))
      .filter((artifact): artifact is TaskRunArtifact => !!artifact);
  }

  /** Peer agent runs this run may message (agent peer messaging discovery). */
  async listTaskRunPeers(
    taskId: string,
    runId: string,
  ): Promise<TaskRunPeer[]> {
    const teamId = this.getTeamId();
    const response = await this.apiRequest<{ peers: TaskRunPeer[] }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/peers/`,
    );
    return response.peers ?? [];
  }

  /**
   * Relay a message from this run to a peer agent run. The synchronous result
   * means `accepted` (queued), never delivered — the sandbox handoff happens
   * later inside the target's workflow.
   */
  async sendTaskRunPeerMessage(
    taskId: string,
    runId: string,
    targetRunId: string,
    payload: { content: string; artifactIds?: string[] },
  ): Promise<PeerMessageSendResult> {
    const teamId = this.getTeamId();
    return this.apiRequest<PeerMessageSendResult>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/peers/${encodeURIComponent(targetRunId)}/message/`,
      {
        method: "POST",
        body: JSON.stringify({
          content: payload.content,
          artifact_ids: payload.artifactIds ?? [],
        }),
      },
    );
  }

  /** Signal reports the given task is associated with (via report task associations). */
  async getSignalReportIdsForTask(
    taskId: string,
    signal?: AbortSignal,
  ): Promise<string[]> {
    const teamId = this.getTeamId();
    const response = await this.apiRequest<{ results?: { id: string }[] }>(
      `/api/projects/${teamId}/signals/reports/?task_id=${encodeURIComponent(taskId)}&limit=100`,
      { signal },
    );
    return (response.results ?? []).map((r) => r.id);
  }

  /**
   * Append a log artefact to a signal report, attributed to `taskId` via the
   * `X-PostHog-Task-Id` header (the server validates it against the token's team).
   */
  async createSignalReportArtefact(
    reportId: string,
    taskId: string,
    body: { artefact_type: string; content: Record<string, unknown> },
    signal?: AbortSignal,
  ): Promise<void> {
    const teamId = this.getTeamId();
    await this.apiRequest(
      `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/`,
      {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "X-PostHog-Task-Id": taskId },
        signal,
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
      const response = await this.performRequestWithRetry(endpoint);

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
