import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { inject, injectable } from "inversify";

export const DESKTOP_FS_CLIENT = Symbol.for(
  "posthog.core.canvas.desktopFsClient",
);

export interface FsEntryBase {
  id: string;
  path: string;
  type?: string;
  ref?: string | null;
  created_at?: string;
}

const MAX_PAGES = 50;

/**
 * Thin shared client for the project's desktop_file_system surface. Resolves
 * the current PostHog project + auth, then forwards to authenticated fetch.
 * Owners of typed FS rows (dashboards, channel tasks, ...) compose this client
 * instead of duplicating the auth + URL construction + pagination boilerplate.
 */
@injectable()
export class DesktopFsClient {
  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  // `suffix` is appended after `.../desktop_file_system/` — e.g. `<id>/`,
  // `?type=task&ref=<id>`, or an action like `<id>/move/`.
  async fetch(suffix: string, init?: RequestInit): Promise<Response> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) throw new Error("No PostHog project selected");
    const url = `${apiHost}/api/projects/${projectId}/desktop_file_system/${suffix}`;
    return this.authService.authenticatedFetch(fetch, url, init);
  }

  async getEntry<T extends FsEntryBase>(
    id: string,
    errorLabel: string,
  ): Promise<T | null> {
    const res = await this.fetch(`${encodeURIComponent(id)}/`);
    if (res.status === 404) return null;
    if (!res.ok)
      throw new Error(`Failed to load ${errorLabel} (${res.status})`);
    return (await res.json()) as T;
  }

  // List rows matching a server-side-filtered query (e.g.
  // `parent=<path>&type=dashboard`), paging until exhausted. Filtering on the
  // backend keeps this to the matching rows instead of walking the whole project
  // file system — the desktop_file_system can hold thousands of rows (one `task`
  // row per task), so an unfiltered scan is both slow and silently truncated by
  // the page cap. Callers should always pass a `parent`/`type` filter.
  async listByQuery<T extends FsEntryBase>(
    query: string,
    errorLabel: string,
  ): Promise<T[]> {
    const all: T[] = [];
    let suffix = `?${query}`;
    for (let i = 0; i < MAX_PAGES; i++) {
      const res = await this.fetch(suffix);
      if (!res.ok)
        throw new Error(`Failed to list ${errorLabel} (${res.status})`);
      const page = (await res.json()) as { next: string | null; results: T[] };
      all.push(...page.results);
      if (!page.next) return all;
      suffix = new URL(page.next).search;
    }
    return all;
  }
}
