import {
  API_TRANSFER_TIMEOUT_MS,
  type ArtifactSource,
  type ArtifactType,
  type PostHogAPIConfig,
  PostHogHttpClient,
  type TaskRun,
  type TaskRunArtifact,
  type TaskRunUpdate,
  transferTimeoutMs,
} from "@posthog/shared";

export { API_TRANSFER_TIMEOUT_MS, transferTimeoutMs, type TaskRunUpdate };

export class TaskToolsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "TaskToolsApiError";
  }
}

export interface TaskArtifactUploadPayload {
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  content: string;
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

export interface TaskArtifactFinalizeUploadPayload {
  id: string;
  name: string;
  type: ArtifactType;
  source?: ArtifactSource;
  storage_path: string;
  content_type?: string;
}

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
  sendable: boolean;
  updated_at: string | null;
}

export interface PeerMessageSendResult {
  result: string;
  detail: string;
  message_id?: string | null;
}

export class TaskToolsApiClient {
  private readonly http: PostHogHttpClient;

  constructor(config: PostHogAPIConfig) {
    this.http = new PostHogHttpClient(config, {
      defaultUserAgent: "posthog/harness.local-tools",
      buildError: (message, status) => new TaskToolsApiError(message, status),
    });
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    payload: TaskRunUpdate,
    signal?: AbortSignal,
  ): Promise<TaskRun> {
    return this.http.updateTaskRun(taskId, runId, payload, signal);
  }

  async reportAnalysisActivity(
    taskId: string,
    runId: string,
    activity: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<{ activity_index: number }> {
    const teamId = this.http.getTeamId();
    return this.http.request<{ activity_index: number }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/analysis-activity/`,
      { method: "POST", body: JSON.stringify(activity), signal },
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
    const teamId = this.http.getTeamId();
    const body = JSON.stringify({ artifacts });
    const response = await this.http.request<{
      artifacts: TaskRunArtifact[];
    }>(`/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/`, {
      method: "POST",
      body,
      signal: AbortSignal.timeout(transferTimeoutMs(body.length)),
    });
    const manifest = response.artifacts ?? [];
    return manifest.slice(-artifacts.length);
  }

  async prepareTaskArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactPrepareUploadPayload[],
  ): Promise<PreparedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }
    const teamId = this.http.getTeamId();
    const response = await this.http.request<{
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

  async finalizeTaskArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactFinalizeUploadPayload[],
  ): Promise<TaskRunArtifact[]> {
    if (!artifacts.length) {
      return [];
    }
    const teamId = this.http.getTeamId();
    const response = await this.http.request<{
      artifacts: TaskRunArtifact[];
    }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/finalize_upload/`,
      {
        method: "POST",
        body: JSON.stringify({ artifacts }),
        signal: AbortSignal.timeout(API_TRANSFER_TIMEOUT_MS),
      },
    );
    const manifest = response.artifacts ?? [];
    const byStoragePath = new Map(
      manifest.map((artifact) => [artifact.storage_path, artifact]),
    );
    return artifacts
      .map((artifact) => byStoragePath.get(artifact.storage_path))
      .filter((artifact): artifact is TaskRunArtifact => !!artifact);
  }

  async listTaskRunPeers(
    taskId: string,
    runId: string,
  ): Promise<TaskRunPeer[]> {
    const teamId = this.http.getTeamId();
    const response = await this.http.request<{ peers: TaskRunPeer[] }>(
      `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/peers/`,
    );
    return response.peers ?? [];
  }

  async sendTaskRunPeerMessage(
    taskId: string,
    runId: string,
    targetRunId: string,
    payload: { content: string; artifactIds?: string[] },
  ): Promise<PeerMessageSendResult> {
    const teamId = this.http.getTeamId();
    return this.http.request<PeerMessageSendResult>(
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

  async getSignalReportIdsForTask(
    taskId: string,
    signal?: AbortSignal,
  ): Promise<string[]> {
    const teamId = this.http.getTeamId();
    const response = await this.http.request<{
      results?: { id: string }[];
    }>(
      `/api/projects/${teamId}/signals/reports/?task_id=${encodeURIComponent(taskId)}&limit=100`,
      { signal },
    );
    return (response.results ?? []).map((r) => r.id);
  }

  async createSignalReportArtefact(
    reportId: string,
    taskId: string,
    body: { artefact_type: string; content: Record<string, unknown> },
    signal?: AbortSignal,
  ): Promise<void> {
    const teamId = this.http.getTeamId();
    await this.http.request(
      `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/`,
      {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "X-PostHog-Task-Id": taskId },
        signal,
      },
    );
  }
}
