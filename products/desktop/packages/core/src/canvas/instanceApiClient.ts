import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { inject, injectable } from "inversify";

export const INSTANCE_API_CLIENT = Symbol.for(
  "posthog.core.canvas.instanceApiClient",
);

/**
 * Thin client for instance-level PostHog REST endpoints, the ones under `/api/` that are not
 * scoped to a project.
 *
 * Separate from `ProjectApiClient` because that one refuses to build a URL without a selected
 * project, which is exactly the situation these endpoints exist to resolve.
 */
@injectable()
export class InstanceApiClient {
  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  // `path` is appended after `/api/` — e.g. `canvas_locations/<id>/`.
  async fetch(path: string, init?: RequestInit): Promise<Response> {
    const { apiHost } = await this.authService.getValidAccessToken();
    return this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/${path}`,
      init,
    );
  }
}
