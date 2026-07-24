import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import type {
  CanvasCaptureConfig,
  CanvasCaptureInput,
  CanvasCaptureResult,
  CanvasDataQueryInput,
  CanvasDataResult,
  CanvasLoadInsightInput,
} from "./freeformSchemas";
import {
  fetchCurrentUser,
  fetchInsightByShortId,
  runQuery,
} from "./posthogApi";

// Last-resort attribution if we can't resolve the signed-in user (and the
// canvas didn't pass its own distinctId).
const FALLBACK_DISTINCT_ID = "freeform-canvas";

/**
 * The host-side data avenue behind a freeform canvas's `ph.query` shim.
 *
 * Runs HogQL through PostHog's cached query runner — the SAME avenue insights
 * use, so caching and cold-boot are handled for us — by passing
 * `refresh: "blocking"` (return a fresh cached result if one exists, else
 * compute synchronously). The PostHog token is injected here via
 * `authenticatedFetch`; it never crosses into the iframe.
 *
 * Edit-mode only for now (inline HogQL). The published/view tier (Phase 3) will
 * reject inline HogQL and require a named, server-stored insight referenced by
 * `ph.run(name, params)`, validated against a per-canvas allowlist.
 */
@injectable()
export class CanvasDataService {
  private readonly log: ScopedLogger;
  // The public capture key (phc_…) per project id. Keyed by project so switching
  // projects in the same session doesn't reuse the previous project's key (this
  // is a singleton service).
  private readonly projectTokens = new Map<number, string>();
  // The signed-in user's distinct_id, the default attribution in edit mode.
  // Per-user (not per-project), so a single cached value is correct.
  private userDistinctId: string | undefined;

  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("canvas-data");
  }

  async query(input: CanvasDataQueryInput): Promise<CanvasDataResult> {
    try {
      // A typed query node (TrendsQuery/etc.) runs as-is so the numbers match the
      // PostHog UI; an inline HogQL string is the escape hatch. Cache-first
      // execution (the insights avenue): serve a fresh cached result if present,
      // otherwise compute it now.
      const isTyped = input.query != null;
      const node = isTyped
        ? (input.query as Record<string, unknown>)
        : { kind: "HogQLQuery", query: input.hogql as string };
      const { columns, results } = await runQuery(this.authService, node, {
        refresh: "blocking",
      });
      return {
        columns,
        // HogQL returns rows; normalise a bare scalar row to a 1-cell array.
        // Typed nodes return SERIES OBJECTS — pass them through untouched (wrapping
        // them in arrays is what made every value read as 0).
        results: isTyped
          ? results
          : results.map((r) => (Array.isArray(r) ? r : [r])),
      };
    } catch (err) {
      this.log.warn("Canvas query failed", {
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }

  // The preferred data avenue: load a SAVED insight by short id and return its
  // STORED result from the insights endpoint (not a fresh /query/ run). The
  // canvas date picker's window rides along as the insight's date override.
  async loadInsight(input: CanvasLoadInsightInput): Promise<CanvasDataResult> {
    try {
      const insight = await fetchInsightByShortId(
        this.authService,
        input.shortId,
        { dateRange: input.dateRange },
      );
      // Mirror the shape handling in `query`: a SQL insight returns rows (coerce a
      // bare scalar row to a 1-cell array); a trends-style insight returns SERIES
      // OBJECTS, which must pass through untouched (wrapping them reads every value
      // as 0).
      const isRows = insight.queryKind === "HogQLQuery";
      return {
        columns: insight.columns,
        results: isRows
          ? insight.results.map((r) => (Array.isArray(r) ? r : [r]))
          : insight.results,
      };
    } catch (err) {
      this.log.warn("Canvas loadInsight failed", {
        shortId: input.shortId,
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }

  // The bootstrap config the iframe needs to run posthog-js (analytics +
  // session replay) itself: the public capture key + the signed-in user's
  // distinct_id. The private read token is never included.
  async captureConfig(): Promise<CanvasCaptureConfig> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) {
      throw new Error("No PostHog project selected");
    }
    const [publicKey, distinctId] = await Promise.all([
      this.getProjectToken(apiHost, projectId),
      this.getUserDistinctId(),
    ]);
    return { apiHost, publicKey, distinctId };
  }

  // Send an analytics event to the host's project using the PUBLIC project key.
  // This is the `ph.capture` avenue: the canvas never holds a key, the host
  // attaches the (safe-to-be-public) capture token and posts the event.
  async capture(input: CanvasCaptureInput): Promise<CanvasCaptureResult> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) {
      throw new Error("No PostHog project selected");
    }

    const apiKey = await this.getProjectToken(apiHost, projectId);
    // Attribution order: an explicit distinctId the canvas passed (e.g. a
    // per-visitor id once sharing exists) wins; otherwise the signed-in user
    // (edit mode); otherwise a stable fallback.
    const distinctId =
      input.distinctId ??
      (await this.getUserDistinctId()) ??
      FALLBACK_DISTINCT_ID;
    const response = await fetch(`${apiHost}/i/v0/e/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey,
        event: input.event,
        distinct_id: distinctId,
        properties: {
          ...input.properties,
          // Mark provenance so these are easy to find/filter in the project.
          $lib: "posthog-canvas",
        },
      }),
    });

    if (!response.ok) {
      this.log.warn("Canvas capture failed", { status: response.status });
      throw new Error(`Capture failed (${response.status})`);
    }
    return { ok: true };
  }

  // The project's public capture key. Fetched from the authenticated project
  // endpoint (which the user can already read) and cached; capture itself uses
  // the public key, not the bearer token.
  private async getProjectToken(
    apiHost: string,
    projectId: number,
  ): Promise<string> {
    const cached = this.projectTokens.get(projectId);
    if (cached) return cached;
    const res = await this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/projects/${projectId}/`,
    );
    if (!res.ok) {
      throw new Error(`Couldn't read project key (${res.status})`);
    }
    const data = (await res.json()) as { api_token?: string };
    if (!data.api_token) throw new Error("Project has no capture key");
    this.projectTokens.set(projectId, data.api_token);
    return data.api_token;
  }

  // The signed-in user's distinct_id (so edit-mode captures attribute to "me" in
  // PostHog, not a placeholder). Cached; returns undefined if unavailable.
  private async getUserDistinctId(): Promise<string | undefined> {
    if (this.userDistinctId !== undefined) return this.userDistinctId;
    const user = await fetchCurrentUser(this.authService);
    this.userDistinctId = user?.distinctId;
    return this.userDistinctId;
  }
}
