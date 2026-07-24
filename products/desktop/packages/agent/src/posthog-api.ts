import packageJson from "../package.json" with { type: "json" };
import type {
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

export interface TaskArtifactUploadPayload {
  name: string;
  type: ArtifactType;
  content: string;
  /** Encoding of `content`. With "base64" the backend stores the decoded bytes. */
  content_encoding?: "utf-8" | "base64";
  content_type?: string;
}

export interface TaskArtifactPrepareUploadPayload {
  name: string;
  type: ArtifactType;
  size: number;
  content_type?: string;
}

export interface PreparedTaskArtifactUpload {
  id: string;
  name: string;
  type: ArtifactType;
  size: number;
  content_type?: string;
  storage_path: string;
  expires_in: number;
  presigned_post: { url: string; fields: Record<string, string> };
}

export interface TaskArtifactFinalizeUploadPayload {
  id: string;
  name: string;
  type: ArtifactType;
  storage_path: string;
  content_type?: string;
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
};

export class PostHogAPIClient {
  private config: PostHogAPIConfig;

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
    headers.set("Content-Type", "application/json");
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

  async getTask(taskId: string): Promise<Task> {
    const teamId = this.getTeamId();
    return this.apiRequest<Task>(`/api/projects/${teamId}/tasks/${taskId}/`);
  }

  async getTaskRun(taskId: string, runId: string): Promise<TaskRun> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
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
  ): Promise<TaskRun> {
    const teamId = this.getTeamId();
    return this.apiRequest<TaskRun>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
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

  async appendTaskRunLog(
    taskId: string,
    runId: string,
    entries: StoredEntry[],
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
    const response = await this.apiRequest<{ artifacts: TaskRunArtifact[] }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/`,
      {
        method: "POST",
        body: JSON.stringify({ artifacts }),
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

  /** Signal reports the given task is associated with (via report task associations). */
  async getSignalReportIdsForTask(taskId: string): Promise<string[]> {
    const teamId = this.getTeamId();
    const response = await this.apiRequest<{ results?: { id: string }[] }>(
      `/api/projects/${teamId}/signals/reports/?task_id=${encodeURIComponent(taskId)}&limit=100`,
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
  ): Promise<void> {
    const teamId = this.getTeamId();
    await this.apiRequest(
      `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/`,
      {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "X-PostHog-Task-Id": taskId },
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
