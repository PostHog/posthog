import type { TaskRun } from "./domain-types";
import type { PostHogAPIConfig } from "./task";

export const API_TRANSFER_TIMEOUT_MS = 30_000;
export const API_DOWNLOAD_TIMEOUT_MS = 300_000;
const MIN_TRANSFER_BYTES_PER_MS = 256;

export function transferTimeoutMs(byteLength: number): number {
  return Math.max(
    API_TRANSFER_TIMEOUT_MS,
    Math.ceil(byteLength / MIN_TRANSFER_BYTES_PER_MS),
  );
}

export class PostHogHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "PostHogHttpError";
  }
}

export type TaskRunUpdate = Partial<
  Pick<
    TaskRun,
    "status" | "branch" | "stage" | "error_message" | "output" | "state"
  >
> & {
  state_remove_keys?: string[];
  state_append?: Record<string, unknown>;
};

export interface PostHogHttpClientOptions {
  defaultUserAgent?: string;
  buildError?: (message: string, status: number) => Error;
}

export class PostHogHttpClient {
  constructor(
    private readonly config: PostHogAPIConfig,
    private readonly options: PostHogHttpClientOptions = {},
  ) {}

  get baseUrl(): string {
    return this.config.apiUrl.endsWith("/")
      ? this.config.apiUrl.slice(0, -1)
      : this.config.apiUrl;
  }

  getTeamId(): number {
    return this.config.projectId;
  }

  async resolveApiKey(forceRefresh = false): Promise<string> {
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
    headers.set(
      "User-Agent",
      this.config.userAgent ??
        this.options.defaultUserAgent ??
        "posthog/api-http-client",
    );
    return headers;
  }

  async performRequest(
    endpoint: string,
    options: RequestInit,
    forceRefresh = false,
  ): Promise<Response> {
    const url = `${this.baseUrl}${endpoint}`;
    return fetch(url, {
      ...options,
      signal: options.signal ?? AbortSignal.timeout(API_TRANSFER_TIMEOUT_MS),
      headers: await this.buildHeaders(options, forceRefresh),
    });
  }

  async performRequestWithRetry(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<Response> {
    let response = await this.performRequest(endpoint, options);
    if (!response.ok && response.status === 401) {
      response = await this.performRequest(endpoint, options, true);
    }
    return response;
  }

  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const response = await this.performRequestWithRetry(endpoint, options);
    if (!response.ok) {
      let errorMessage: string;
      try {
        const errorResponse = await response.json();
        errorMessage = `Failed request: [${response.status}] ${JSON.stringify(errorResponse)}`;
      } catch {
        errorMessage = `Failed request: [${response.status}] ${response.statusText}`;
      }
      const buildError =
        this.options.buildError ??
        ((message: string, status: number) =>
          new PostHogHttpError(message, status));
      throw buildError(errorMessage, response.status);
    }
    return (await response.json()) as T;
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    payload: TaskRunUpdate,
    signal?: AbortSignal,
  ): Promise<TaskRun> {
    return this.request<TaskRun>(
      `/api/projects/${this.getTeamId()}/tasks/${taskId}/runs/${runId}/`,
      { method: "PATCH", body: JSON.stringify(payload), signal },
    );
  }
}
