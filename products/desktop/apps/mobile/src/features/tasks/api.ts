import type { Adapter } from "@posthog/shared";
import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { fetch } from "expo/fetch";
import {
  authedFetch,
  createTimeoutSignal,
  getAccessToken,
  getBaseUrl,
  getProjectId,
} from "@/lib/api";
import { logger } from "@/lib/logger";
import type {
  CreateTaskAutomationOptions,
  CreateTaskOptions,
  Integration,
  StoredLogEntry,
  Task,
  TaskAutomation,
  TaskRun,
  UpdateTaskAutomationOptions,
  UserGithubIntegration,
} from "./types";

const log = logger.scope("tasks-api");

export class HttpError extends Error {
  readonly status: number;

  constructor(status: number, statusText: string, prefix: string) {
    super(`${prefix}: ${status} ${statusText}`);
    this.name = "HttpError";
    this.status = status;
  }
}

export class TaskAutomationValidationError extends Error {
  readonly code: string;
  readonly attr: string | null;

  constructor(message: string, code: string, attr: string | null) {
    super(message);
    this.name = "TaskAutomationValidationError";
    this.code = code;
    this.attr = attr;
  }
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

async function parseTaskAutomationError(response: Response): Promise<never> {
  let payload: {
    code?: string;
    detail?: string;
    attr?: string;
  } | null = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (response.status === 400 && payload?.detail) {
    throw new TaskAutomationValidationError(
      payload.detail,
      payload.code ?? "invalid_input",
      payload.attr ?? null,
    );
  }

  throw new HttpError(
    response.status,
    response.statusText,
    "Task automation request failed",
  );
}

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

export async function getTasks(filters?: {
  repository?: string;
  createdBy?: number;
  originProduct?: string;
}): Promise<Task[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const params = new URLSearchParams({ limit: "500" });
  if (filters?.repository) {
    params.set("repository", filters.repository);
  }
  if (filters?.createdBy) {
    params.set("created_by", String(filters.createdBy));
  }
  if (filters?.originProduct) {
    params.set("origin_product", filters.originProduct);
  }

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/?${params}`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch tasks",
    );
  }

  const data = await parseJsonResponse<{ results?: Task[] }>(response);
  return data.results ?? [];
}

export async function getTask(taskId: string): Promise<Task> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch task",
    );
  }

  return await parseJsonResponse<Task>(response);
}

export async function getTaskAutomations(): Promise<TaskAutomation[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/?limit=500`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch task automations",
    );
  }

  const data = await parseJsonResponse<{ results?: TaskAutomation[] }>(
    response,
  );
  return data.results ?? [];
}

export async function getTaskAutomation(
  automationId: string,
): Promise<TaskAutomation> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/${automationId}/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch task automation",
    );
  }

  return await parseJsonResponse<TaskAutomation>(response);
}

export async function createTaskAutomation(
  options: CreateTaskAutomationOptions,
): Promise<TaskAutomation> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/`,
    {
      method: "POST",
      body: JSON.stringify(options),
    },
  );

  if (!response.ok) {
    await parseTaskAutomationError(response);
  }

  return await parseJsonResponse<TaskAutomation>(response);
}

export async function updateTaskAutomation(
  automationId: string,
  updates: UpdateTaskAutomationOptions,
): Promise<TaskAutomation> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/${automationId}/`,
    {
      method: "PATCH",
      body: JSON.stringify(updates),
    },
  );

  if (!response.ok) {
    await parseTaskAutomationError(response);
  }

  return await parseJsonResponse<TaskAutomation>(response);
}

export async function deleteTaskAutomation(
  automationId: string,
): Promise<void> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/${automationId}/`,
    { method: "DELETE" },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to delete task automation",
    );
  }
}

export async function runTaskAutomation(
  automationId: string,
): Promise<TaskAutomation> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/task_automations/${automationId}/run/`,
    { method: "POST" },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to run task automation",
    );
  }

  return await parseJsonResponse<TaskAutomation>(response);
}

export async function warmTask(options: {
  repository: string;
  github_integration: number;
  branch?: string | null;
  runtime_adapter?: string | null;
  model?: string | null;
  reasoning_effort?: string | null;
  sandbox_environment_id?: string | null;
  custom_image_id?: string | null;
}): Promise<{ task_id: string; run_id: string } | null> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/warm/`,
    {
      method: "POST",
      body: JSON.stringify({
        repository: options.repository,
        github_integration: options.github_integration,
        branch: options.branch ?? null,
        runtime_adapter: options.runtime_adapter ?? null,
        model: options.model ?? null,
        reasoning_effort: options.reasoning_effort ?? null,
        ...(options.sandbox_environment_id
          ? { sandbox_environment_id: options.sandbox_environment_id }
          : {}),
        ...(options.custom_image_id
          ? { custom_image_id: options.custom_image_id }
          : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to warm task",
    );
  }

  const text = await response.text();
  if (!text) {
    return null;
  }
  return JSON.parse(text) as { task_id: string; run_id: string };
}

export async function createTask(options: CreateTaskOptions): Promise<Task> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/`,
    {
      method: "POST",
      body: JSON.stringify({
        origin_product: "user_created",
        ...options,
      }),
    },
  );

  if (!response.ok) {
    const errorText = await response.text();
    log.error("Create task error", errorText);
    throw new HttpError(
      response.status,
      `${response.statusText} - ${errorText}`,
      "Failed to create task",
    );
  }

  return await parseJsonResponse<Task>(response);
}

export async function updateTask(
  taskId: string,
  updates: Partial<Task>,
): Promise<Task> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/`,
    {
      method: "PATCH",
      body: JSON.stringify(updates),
    },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to update task",
    );
  }

  return await parseJsonResponse<Task>(response);
}

export async function deleteTask(taskId: string): Promise<void> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/`,
    { method: "DELETE" },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to delete task",
    );
  }
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
  /** Sandbox environment / custom base image to run on. Sent so a reused warm
   *  sandbox matches the selection instead of a mismatched default. */
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
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
}

export async function runTaskInCloud(
  taskId: string,
  options?: RunTaskInCloudOptions,
): Promise<Task> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  // Only serialize a body when we have options to send. Sending an empty
  // or minimal body on the initial run historically changed backend
  // behavior, so we preserve the "no body" path for the common case.
  const hasOptions =
    !!options &&
    (options.branch !== undefined ||
      options.resumeFromRunId !== undefined ||
      options.pendingUserMessage !== undefined ||
      options.mode !== undefined ||
      options.runtimeAdapter !== undefined ||
      options.model !== undefined ||
      options.reasoningEffort !== undefined ||
      options.sandboxEnvironmentId !== undefined ||
      options.customImageId !== undefined ||
      options.initialPermissionMode !== undefined ||
      options.runSource !== undefined ||
      options.signalReportId !== undefined ||
      options.autoPublish !== undefined ||
      options.rtkEnabled === false);

  let body: string | undefined;
  if (hasOptions) {
    const payload: Record<string, unknown> = {
      mode: options?.mode ?? "interactive",
    };
    if (options?.branch) payload.branch = options.branch;
    if (options?.resumeFromRunId) {
      payload.resume_from_run_id = options.resumeFromRunId;
    }
    if (options?.pendingUserMessage) {
      payload.pending_user_message = options.pendingUserMessage;
    }
    if (options?.runtimeAdapter) {
      payload.runtime_adapter = options.runtimeAdapter;
      if (options?.model) payload.model = options.model;
      if (options?.reasoningEffort) {
        payload.reasoning_effort = options.reasoningEffort;
      }
    }
    if (options?.sandboxEnvironmentId) {
      payload.sandbox_environment_id = options.sandboxEnvironmentId;
    }
    if (options?.customImageId) {
      payload.custom_image_id = options.customImageId;
    }
    if (options?.initialPermissionMode) {
      payload.initial_permission_mode = options.initialPermissionMode;
    }
    if (options?.runSource) payload.run_source = options.runSource;
    if (options?.signalReportId)
      payload.signal_report_id = options.signalReportId;
    if (options?.autoPublish !== undefined) {
      payload.auto_publish = options.autoPublish;
    }
    if (options?.rtkEnabled === false) {
      payload.rtk_enabled = false;
    }
    body = JSON.stringify(payload);
  }

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/run/`,
    {
      method: "POST",
      body,
    },
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to run task",
    );
  }

  return await response.json();
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

export interface SessionLogsPage {
  entries: StoredLogEntry[];
  hasMore: boolean;
}

export async function fetchSessionLogs(
  taskId: string,
  runId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<SessionLogsPage> {
  return withRetry(
    async () => {
      const baseUrl = getBaseUrl();
      const projectId = getProjectId();

      const params = new URLSearchParams({
        limit: String(options.limit ?? 5000),
        offset: String(options.offset ?? 0),
      });

      const response = await authedFetch(
        `${baseUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/session_logs/?${params}`,
        { signal: createTimeoutSignal(10_000) },
      );

      if (!response.ok) {
        throw new HttpError(
          response.status,
          response.statusText,
          "Failed to fetch session logs",
        );
      }

      const entries = (await response.json()) as StoredLogEntry[];
      return {
        entries,
        hasMore: response.headers.get("X-Has-More") === "true",
      };
    },
    { shouldRetry: isRetryableError },
  );
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

export async function getSandboxCustomImages(): Promise<SandboxCustomImage[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/sandbox_custom_images/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch sandbox custom images",
    );
  }

  const data = await parseJsonResponse<{ results?: SandboxCustomImage[] }>(
    response,
  );
  return data.results ?? [];
}

export async function getSandboxEnvironments(): Promise<SandboxEnvironment[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/sandbox_environments/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch sandbox environments",
    );
  }

  const data = await parseJsonResponse<{ results?: SandboxEnvironment[] }>(
    response,
  );
  return data.results ?? [];
}

export async function getIntegrations(): Promise<Integration[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/environments/${projectId}/integrations/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch integrations",
    );
  }

  const data = await parseJsonResponse<
    | {
        results?: Integration[];
      }
    | Integration[]
  >(response);
  return Array.isArray(data) ? data : (data.results ?? []);
}

const GITHUB_REPOS_PAGE_SIZE = 500;

export async function getGithubRepositories(
  integrationId: number,
): Promise<string[]> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const allRepos: string[] = [];
  let offset = 0;

  while (true) {
    const params = new URLSearchParams({
      limit: String(GITHUB_REPOS_PAGE_SIZE),
      offset: String(offset),
    });
    const response = await authedFetch(
      `${baseUrl}/api/environments/${projectId}/integrations/${integrationId}/github_repos/?${params}`,
    );

    if (!response.ok) {
      throw new HttpError(
        response.status,
        response.statusText,
        "Failed to fetch repositories",
      );
    }

    const data = await response.json();
    const repos: Array<string | { full_name?: string; name?: string }> =
      data.repositories ?? data.results ?? data ?? [];

    const normalized = repos
      .map((repo) => {
        if (typeof repo === "string") return repo.toLowerCase();
        return (repo.full_name ?? repo.name ?? "").toLowerCase();
      })
      .filter((name) => name.length > 0);

    allRepos.push(...normalized);

    if (!data.has_more || repos.length === 0) {
      return allRepos;
    }

    offset += repos.length;
  }
}

export interface GithubUserConnectResult {
  install_url: string;
  connect_flow?: "oauth_authorize" | "oauth_discover" | "app_install";
}

/**
 * Starts the user-scoped GitHub connection flow (mirrors desktop). The backend
 * picks the lightweight OAuth flow when the team already has the GitHub App
 * installed, otherwise a discover/install flow, and returns the URL to open.
 *
 * `connect_from: "posthog_mobile"` tells the backend to redirect the OAuth
 * callback to `posthog://github/callback` so the in-app browser auto-closes.
 */
export async function startGithubUserIntegrationConnect(): Promise<GithubUserConnectResult> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/users/@me/integrations/github/start/`,
    {
      method: "POST",
      body: JSON.stringify({
        team_id: projectId,
        connect_from: "posthog_mobile",
      }),
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : "Failed to start GitHub connection";
    throw new HttpError(response.status, response.statusText, detail);
  }

  return parseJsonResponse<GithubUserConnectResult>(response);
}

export async function getUserGithubIntegrations(): Promise<
  UserGithubIntegration[]
> {
  const baseUrl = getBaseUrl();

  const response = await authedFetch(
    `${baseUrl}/api/users/@me/integrations/?kind=github`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch personal GitHub integrations",
    );
  }

  const data = await parseJsonResponse<{ results?: UserGithubIntegration[] }>(
    response,
  );
  return data.results ?? [];
}

export async function getUserGithubRepositories(
  installationId: string,
): Promise<string[]> {
  const baseUrl = getBaseUrl();

  const allRepos: string[] = [];
  let offset = 0;

  while (true) {
    const params = new URLSearchParams({
      limit: String(GITHUB_REPOS_PAGE_SIZE),
      offset: String(offset),
    });
    const response = await authedFetch(
      `${baseUrl}/api/users/@me/integrations/github/${installationId}/repos/?${params}`,
    );

    if (!response.ok) {
      throw new HttpError(
        response.status,
        response.statusText,
        "Failed to fetch repositories",
      );
    }

    const data = await response.json();
    const repos: Array<string | { full_name?: string; name?: string }> =
      data.repositories ?? data.results ?? data ?? [];

    const normalized = repos
      .map((repo) => {
        if (typeof repo === "string") return repo.toLowerCase();
        return (repo.full_name ?? repo.name ?? "").toLowerCase();
      })
      .filter((name) => name.length > 0);

    allRepos.push(...normalized);

    if (!data.has_more || repos.length === 0) {
      return allRepos;
    }

    offset += repos.length;
  }
}
