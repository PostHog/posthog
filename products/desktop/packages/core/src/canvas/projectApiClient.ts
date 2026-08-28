import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { inject, injectable } from "inversify";

export const PROJECT_API_CLIENT = Symbol.for(
  "posthog.core.canvas.projectApiClient",
);

const MAX_PAGES = 50;

/** An API call that failed with an HTTP status (so callers can branch on it). */
export class ProjectApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ProjectApiError";
  }
}

/** The status code of a ProjectApiError, or null for a non-API error. */
export function apiErrorStatus(error: unknown): number | null {
  return error instanceof ProjectApiError ? error.status : null;
}

// A DRF error body carries the actual cause ("detail", plus canvas validation
// "diagnostics"); without it a 400 is undiagnosable from the client. Cap the
// diagnostics so one broken layout doesn't produce a screen-length message.
const MAX_ERROR_DIAGNOSTICS = 5;

async function errorBodyDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (typeof body !== "object" || body === null) return "";
    const parts: string[] = [];
    const { detail, diagnostics } = body as {
      detail?: unknown;
      diagnostics?: unknown;
    };
    if (typeof detail === "string" && detail) parts.push(detail);
    if (Array.isArray(diagnostics)) {
      for (const diagnostic of diagnostics.slice(0, MAX_ERROR_DIAGNOSTICS)) {
        const message = (diagnostic as { message?: unknown } | null)?.message;
        if (typeof message === "string" && message) parts.push(message);
      }
      if (diagnostics.length > MAX_ERROR_DIAGNOSTICS) {
        parts.push(`(+${diagnostics.length - MAX_ERROR_DIAGNOSTICS} more)`);
      }
    }
    return parts.length > 0 ? `: ${parts.join(" ")}` : "";
  } catch {
    return "";
  }
}

/**
 * Thin shared client for the current PostHog project's REST API. Resolves the
 * project + auth, then forwards to authenticated fetch. Owners of typed
 * resources (canvases, channel tasks, ...) compose this client instead of
 * duplicating the auth + URL construction + pagination boilerplate.
 */
@injectable()
export class ProjectApiClient {
  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  // `path` is appended after `/api/projects/<id>/` — e.g. `canvases/<id>/`.
  async fetch(path: string, init?: RequestInit): Promise<Response> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) throw new Error("No PostHog project selected");
    const url = `${apiHost}/api/projects/${projectId}/${path}`;
    return this.authService.authenticatedFetch(fetch, url, init);
  }

  async json<T>(
    path: string,
    errorLabel: string,
    init?: RequestInit,
  ): Promise<T> {
    const res = await this.fetch(path, init);
    if (!res.ok)
      throw new ProjectApiError(
        `Failed to ${errorLabel} (${res.status})${await errorBodyDetail(res)}`,
        res.status,
      );
    return (await res.json()) as T;
  }

  /**
   * List a DRF-paginated collection, walking `next` links until exhausted.
   * `options.limit` sets the page size on the first request (subsequent pages
   * follow the server's `next` links, which carry the limit forward).
   */
  async listPaginated<T>(
    path: string,
    errorLabel: string,
    options?: { limit?: number },
  ): Promise<T[]> {
    const all: T[] = [];
    let suffix =
      options?.limit != null
        ? `${path}${path.includes("?") ? "&" : "?"}limit=${options.limit}`
        : path;
    for (let i = 0; i < MAX_PAGES; i++) {
      const page = await this.json<{ next: string | null; results: T[] }>(
        suffix,
        errorLabel,
      );
      all.push(...page.results);
      if (!page.next) return all;
      const next = new URL(page.next);
      suffix = `${next.pathname.replace(/^.*\/api\/projects\/[^/]+\//, "")}${next.search}`;
    }
    return all;
  }
}
