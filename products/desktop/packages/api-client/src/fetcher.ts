import type { createApiClient } from "./generated";

export type FetchImplementation = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type ApiRequestMetricRequest = {
  method: string;
  path: string;
};

export type ApiRequestMetricResult = {
  durationMs: number;
  outcome: "success" | "http_error" | "network_error";
  status: number | null;
};

export type ApiRequestMetricRecorder = (result: ApiRequestMetricResult) => void;

type ApiFetcherConfig = {
  getAccessToken: () => Promise<string>;
  refreshAccessToken: () => Promise<string>;
  appVersion: string;
  fetch?: FetchImplementation;
  userAgent?: string | null;
  onRequestStart?: (
    request: ApiRequestMetricRequest,
  ) => ApiRequestMetricRecorder | undefined;
};

/**
 * Non-2xx HTTP response from the PostHog API. Keeps the legacy
 * `Failed request: [<status>] <body>` message format — many catch sites
 * string-match on it — while exposing the status as a typed field.
 */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, serializedBody: string, body?: unknown) {
    super(`Failed request: [${status}] ${serializedBody}`);
    this.name = "ApiRequestError";
    this.status = status;
    this.body = body;
  }
}

/** HTTP status of an ApiRequestError, or undefined for any other error. */
export function requestErrorStatus(error: unknown): number | undefined {
  return error instanceof ApiRequestError ? error.status : undefined;
}

// A 403 is a rejected token only when its body's `code` says so. A permission
// denial shares `type: "authentication_error"` but carries
// `code: "permission_denied"`, and a fresh token cannot fix it.
export async function isAuthFailureResponse(
  response: Response,
): Promise<boolean> {
  if (response.status === 401) return true;
  if (response.status !== 403) return false;
  try {
    const body = (await response.clone().json()) as {
      code?: string;
    } | null;
    return body?.code === "authentication_failed";
  } catch {
    return false;
  }
}

export const buildApiFetcher: (
  config: ApiFetcherConfig,
) => Parameters<typeof createApiClient>[0] = (config) => {
  const fetchImpl = config.fetch ?? globalThis.fetch;
  const userAgent =
    config.userAgent === undefined
      ? `posthog/desktop.hog.dev; version: ${config.appVersion}`
      : config.userAgent;

  const makeRequest = async (
    input: Parameters<Parameters<typeof createApiClient>[0]["fetch"]>[0],
    token: string,
  ): Promise<Response> => {
    const headers = new Headers();
    headers.set("Authorization", `Bearer ${token}`);
    headers.set("Content-Type", "application/json");
    if (userAgent) {
      headers.set("User-Agent", userAgent);
    }

    if (input.urlSearchParams) {
      input.url.search = input.urlSearchParams.toString();
    }

    const body = ["post", "put", "patch", "delete"].includes(
      input.method.toLowerCase(),
    )
      ? JSON.stringify(input.parameters?.body)
      : undefined;

    if (input.parameters?.header) {
      for (const [key, value] of Object.entries(input.parameters.header)) {
        if (value != null) {
          headers.set(key, String(value));
        }
      }
    }

    try {
      const response = await fetchImpl(input.url, {
        method: input.method.toUpperCase(),
        ...(body && { body }),
        headers,
        ...input.overrides,
      });

      return response;
    } catch (err) {
      throw new Error(
        `Network request failed for ${input.method.toUpperCase()} ${input.url}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        { cause: err instanceof Error ? err : undefined },
      );
    }
  };

  return {
    fetch: async (input) => {
      const startedAt = performance.now();
      const recordRequest = config.onRequestStart?.({
        method: input.method.toUpperCase(),
        path: input.path,
      });
      let response: Response | undefined;
      let outcome: ApiRequestMetricResult["outcome"] = "network_error";

      try {
        response = await makeRequest(input, await config.getAccessToken());

        if (!response.ok && (await isAuthFailureResponse(response))) {
          try {
            response = await makeRequest(
              input,
              await config.refreshAccessToken(),
            );
          } catch {
            const failedResponse = response;
            const cloned = failedResponse.clone();
            const errorResponse = await failedResponse
              .json()
              .catch(() =>
                cloned
                  .text()
                  .then((t) => ({ error: t || `${failedResponse.status}` })),
              );
            throw new ApiRequestError(
              failedResponse.status,
              JSON.stringify(errorResponse),
              errorResponse,
            );
          }
        }

        if (!response.ok) {
          const failedResponse = response;
          const cloned = failedResponse.clone();
          const errorResponse = await failedResponse
            .json()
            .catch(() =>
              cloned
                .text()
                .then((t) => ({ error: t || `${failedResponse.status}` })),
            );
          throw new ApiRequestError(
            failedResponse.status,
            JSON.stringify(errorResponse),
            errorResponse,
          );
        }

        outcome = "success";
        return response;
      } catch (error) {
        if (response) {
          outcome = "http_error";
        }
        throw error;
      } finally {
        recordRequest?.({
          durationMs: performance.now() - startedAt,
          outcome,
          status: response?.status ?? null,
        });
      }
    },
  };
};
