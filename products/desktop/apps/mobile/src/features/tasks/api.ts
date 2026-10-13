import type {
  Adapter,
  ExecutionMode,
  StoredLogEntry,
  Task,
  TaskRun,
  TaskRunArtifact,
} from "@posthog/shared";
import { fetch } from "expo/fetch";
import {
  authedFetch,
  getAccessToken,
  getBaseUrl,
  getProjectId,
  HttpError,
} from "@/lib/api";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

export { HttpError } from "@/lib/api";

async function withRetry<T>(
  fn: () => Promise<T>,
  options: {
    maxRetries?: number;
    baseDelayMs?: number;
    shouldRetry?: (error: unknown) => boolean;
  } = {},
): Promise<T> {
  const { maxRetries = 3, baseDelayMs = 200, shouldRetry } = options;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      const isLastAttempt = attempt === maxRetries;
      const canRetry = shouldRetry ? shouldRetry(error) : true;

      if (isLastAttempt || !canRetry) {
        throw error;
      }

      const delay = baseDelayMs * 2 ** (attempt - 1);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw new Error("Unreachable");
}

function isRetryableError(error: unknown): boolean {
  if (
    error instanceof Error &&
    "status" in error &&
    typeof error.status === "number"
  ) {
    return error.status >= 500 && error.status < 600;
  }
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    if (message.includes("network")) return true;
    if (message.includes("timeout")) return true;
    if (message.includes("econnreset")) return true;
  }
  return false;
}

export interface RunTaskInCloudOptions {
  branch?: string | null;
  resumeFromRunId?: string;
  pendingUserMessage?: string;
  mode?: "interactive" | "background";
  /** Adapter to use on the cloud runner. Currently only "claude" on mobile. */
  runtimeAdapter?: Adapter;
  /** Gateway model ID, e.g. "claude-opus-4-8". */
  model?: string;
  /** Reasoning effort: "low" | "medium" | "high" (model-dependent). */
  reasoningEffort?: string;
  /** Context window size; only sent for models that support the 1M beta. */
  contextWindow?: "200k" | "1m";
  /** Fast mode; only sent for models that support it. */
  fastMode?: boolean;
  /** Permission mode: "default" | "acceptEdits" | "plan" | "auto". */
  initialPermissionMode?: string;
  /** Source that triggered this run. */
  runSource?: "manual" | "signal_report";
  /** Signal report ID when run_source is "signal_report". */
  signalReportId?: string;
  /** When true, the cloud run pushes its changes and opens a draft PR on
   *  completion without waiting for an explicit ask. */
  autoPublish?: boolean;
  /** Only false is sent: opts the run out of rtk command-output compression. */
  rtkEnabled?: boolean;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

export async function runTaskInCloud(
  taskId: string,
  options?: RunTaskInCloudOptions,
): Promise<Task> {
  if (!options) {
    return getPostHogApiClient().runTaskInCloud(taskId);
  }

  return getPostHogApiClient().runTaskInCloud(taskId, options.branch, {
    adapter: options.runtimeAdapter,
    model: options.model,
    reasoningLevel: options.reasoningEffort,
    contextWindow: options.contextWindow,
    fastMode: options.fastMode,
    initialPermissionMode: options.initialPermissionMode as
      | ExecutionMode
      | undefined,
    runSource: options.runSource,
    signalReportId: options.signalReportId,
    autoPublish: options.autoPublish,
    rtkEnabled: options.rtkEnabled,
    sandboxEnvironmentId: options.sandboxEnvironmentId ?? undefined,
    customImageId: options.customImageId ?? undefined,
    resumeFromRunId: options.resumeFromRunId,
    pendingUserMessage: options.pendingUserMessage,
  });
}

export async function getTaskRun(
  taskId: string,
  runId: string,
): Promise<TaskRun> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch task run",
    );
  }

  return await response.json();
}

/**
 * Exchanges an artifact's storage path for a short-lived presigned S3 URL used
 * to render image attachment previews.
 */
export async function presignTaskRunArtifact(
  taskId: string,
  runId: string,
  storagePath: string,
): Promise<string> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/artifacts/presign/`,
    {
      method: "POST",
      body: JSON.stringify({ storage_path: storagePath }),
    },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to generate artifact preview URL",
    );
  }

  const data = (await response.json()) as { url: string };
  return data.url;
}

/** Hides or restores every version of a file on the run, returning the updated manifest. */
export async function dismissTaskRunArtifacts(
  taskId: string,
  runId: string,
  artifactIds: string[],
  dismissed: boolean,
): Promise<TaskRunArtifact[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/artifacts/dismiss/`,
    {
      method: "POST",
      body: JSON.stringify({ artifact_ids: artifactIds, dismissed }),
    },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to update artifact",
    );
  }

  const data = (await response.json()) as { artifacts?: TaskRunArtifact[] };
  return data.artifacts ?? [];
}

export async function cancelRun(
  taskId: string,
  runId: string,
  reason?: string,
): Promise<{ status?: string }> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/cancel/`,
    {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: unknown;
    } | null;
    const message =
      typeof payload?.error === "string" && payload.error
        ? payload.error
        : "Failed to stop run";
    throw new HttpError(response.status, response.statusText, message);
  }

  return (await response.json().catch(() => ({}))) as { status?: string };
}

export async function appendTaskRunLog(
  taskId: string,
  runId: string,
  entries: StoredLogEntry[],
): Promise<void> {
  return withRetry(
    async () => {
      const baseUrl = getBaseUrl();
      const projectId = getProjectId();

      const response = await authedFetch(
        `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/append_log/`,
        {
          method: "POST",
          body: JSON.stringify({ entries }),
        },
      );

      if (!response.ok) {
        throw new HttpError(
          response.status,
          response.statusText,
          "Failed to append log",
        );
      }
    },
    { shouldRetry: isRetryableError },
  );
}

/**
 * Structured error thrown by `sendCloudCommand`. Exposes the HTTP status and
 * the backend error payload so callers can branch on specific failure modes
 * (e.g. "No active sandbox for this task run" → trigger a resume flow).
 */
export class CloudCommandError extends Error {
  readonly status: number;
  readonly backendError: string | null;
  readonly method: string;

  constructor(
    method: string,
    status: number,
    backendError: string | null,
    message: string,
  ) {
    super(message);
    this.name = "CloudCommandError";
    this.method = method;
    this.status = status;
    this.backendError = backendError;
  }

  /** True when the cloud sandbox for this run has terminated. */
  isSandboxInactive(): boolean {
    return (
      !!this.backendError?.includes("No active sandbox") ||
      !!this.backendError?.includes("returned 404") ||
      this.status === 404
    );
  }
}

/**
 * Sends a JSON-RPC command to a running cloud task. This is the correct path
 * for delivering follow-up user prompts to the agent — it gets translated into
 * `session/prompt` on the agent side. Note: `appendTaskRunLog` only writes to
 * S3 for display; it does NOT notify the agent.
 */
export async function sendCloudCommand(
  taskId: string,
  runId: string,
  method: string,
  params: Record<string, unknown> = {},
): Promise<unknown> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const body = {
    jsonrpc: "2.0",
    method,
    params,
    id: `posthog-mobile-${Date.now()}`,
  };

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/command/`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let backendError: string | null = null;
    try {
      const parsed = JSON.parse(text);
      backendError =
        typeof parsed?.error === "string"
          ? parsed.error
          : (parsed?.error?.message ?? null);
    } catch {
      backendError = text || null;
    }
    throw new CloudCommandError(
      method,
      response.status,
      backendError,
      `Cloud command '${method}' failed: ${response.status} ${response.statusText} ${text}`,
    );
  }

  const data = await response.json();
  if (data?.error) {
    const message =
      typeof data.error === "string"
        ? data.error
        : (data.error.message ?? JSON.stringify(data.error));
    throw new CloudCommandError(
      method,
      200,
      message,
      `Cloud command '${method}' error: ${message}`,
    );
  }
  return data?.result;
}

export interface StreamCloudTaskOptions {
  lastEventId?: string | null;
  startLatest?: boolean;
  signal: AbortSignal;
}

export async function streamCloudTask(
  taskId: string,
  runId: string,
  options: StreamCloudTaskOptions,
): Promise<Response> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();
  const accessToken = getAccessToken();

  const url = new URL(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/stream/`,
  );
  if (options.startLatest && !options.lastEventId) {
    url.searchParams.set("start", "latest");
  }

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${accessToken}`,
  };
  if (options.lastEventId) {
    headers["Last-Event-ID"] = options.lastEventId;
  }

  return await fetch(url.toString(), {
    method: "GET",
    headers,
    signal: options.signal,
  });
}
