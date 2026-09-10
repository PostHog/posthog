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
  readCachedQuery,
  runQuery,
} from "./posthogApi";

// Last-resort attribution if we can't resolve the signed-in user (and the
// canvas didn't pass its own distinctId).
const FALLBACK_DISTINCT_ID = "freeform-canvas";
const MAX_CANVAS_RESULT_ROWS = 1_000;
const MAX_CANVAS_RESULT_BYTES = 2 * 1024 * 1024;
// Floor between background recomputes of one stale query (see `revalidate`).
const REVALIDATE_MIN_INTERVAL_MS = 30_000;
const MAX_REVALIDATION_ENTRIES = 512;

const utf8Encoder = new TextEncoder();

// True when the JSON's UTF-8 encoding exceeds the byte limit. UTF-8 is 1–3
// bytes per UTF-16 code unit, so the string length bounds the byte count from
// both sides — only payloads in the ambiguous band pay for a full encode.
function exceedsByteLimit(json: string): boolean {
  if (json.length > MAX_CANVAS_RESULT_BYTES) return true;
  if (json.length * 3 <= MAX_CANVAS_RESULT_BYTES) return false;
  return utf8Encoder.encode(json).byteLength > MAX_CANVAS_RESULT_BYTES;
}

function boundedResult(result: CanvasDataResult): CanvasDataResult {
  if (
    result.results.length > MAX_CANVAS_RESULT_ROWS ||
    exceedsByteLimit(JSON.stringify(result))
  ) {
    throw new Error("Canvas data result exceeds the result limit");
  }
  return result;
}

// Compare a requested SQL-variable value against the one the server resolved.
// Values round-trip verbatim, so structural equality is enough; `undefined`
// normalizes to null because that's how it serializes over the wire.
function sameVariableValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/**
 * Fail loudly when a requested SQL variable didn't actually take effect.
 *
 * The insights API drops an override whose `code_name` matches no variable on the
 * insight, and ignores overrides wholesale under sharing-token auth. Both are
 * SILENT: the insight then computes from its own saved defaults and returns numbers
 * that look real. On a per-product board that means every product rendering the
 * insight's default product — precisely the wrong-but-plausible data a canvas must
 * never show. So verify against what the server says it used, and refuse otherwise.
 */
function assertVariablesApplied(
  requested: Record<string, unknown> | undefined,
  resolved: Record<string, unknown>,
  shortId: string,
): void {
  for (const [codeName, requestedValue] of Object.entries(requested ?? {})) {
    if (!(codeName in resolved)) {
      const known = Object.keys(resolved);
      throw new Error(
        `Insight "${shortId}" has no SQL variable "${codeName}" (it uses: ${known.length > 0 ? known.join(", ") : "none"})`,
      );
    }
    if (!sameVariableValue(resolved[codeName], requestedValue)) {
      throw new Error(
        `SQL variable "${codeName}" was not applied to insight "${shortId}" — it resolved to ${JSON.stringify(resolved[codeName])}, not ${JSON.stringify(requestedValue)}`,
      );
    }
  }
}

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
  // Epoch ms of each query's last background-recompute kickoff (see `revalidate`).
  private readonly revalidatedAt = new Map<string, number>();

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
      // PostHog UI; an inline HogQL string is the escape hatch.
      const isTyped = input.query != null;
      const node = isTyped
        ? (input.query as Record<string, unknown>)
        : { kind: "HogQLQuery", query: input.hogql as string };
      // Shape handling: HogQL returns rows (normalise a bare scalar row to a
      // 1-cell array); typed nodes return SERIES OBJECTS, passed through
      // untouched (wrapping them in arrays is what made every value read as 0).
      const shaped = (results: unknown[]): unknown[] =>
        isTyped ? results : results.map((r) => (Array.isArray(r) ? r : [r]));

      // A canvas that declared a refresh window is a live surface: it re-reads
      // on its own cadence, so it gets dashboard semantics. Any cached result
      // paints immediately, and one older than the window is revalidated in the
      // background so the NEXT read is fresh. A canvas with no window keeps the
      // one-shot semantics: a fresh-enough cached result, else a blocking
      // compute.
      if (input.refresh != null) {
        // The cache probe is an optimization; a transient failure on it must
        // not fail a read that the blocking path below could still serve.
        const cached = await readCachedQuery(this.authService, node).catch(
          (err) => {
            this.log.warn("Canvas cached-read probe failed", {
              error: err instanceof Error ? err.message : String(err),
            });
            return null;
          },
        );
        if (cached) {
          const age =
            cached.lastRefresh != null
              ? Date.now() - Date.parse(cached.lastRefresh)
              : Number.POSITIVE_INFINITY;
          const stale = !(age <= input.refresh * 1_000);
          if (stale) this.revalidate(node);
          return boundedResult({
            columns: cached.columns,
            results: shaped(cached.results),
            ...(stale ? { stale: true } : {}),
          });
        }
      }
      // Cache-first execution (the insights avenue): serve a fresh cached
      // result if present, otherwise compute it now.
      const { columns, results } = await runQuery(this.authService, node, {
        refresh: "blocking",
      });
      return boundedResult({ columns, results: shaped(results) });
    } catch (err) {
      this.log.warn("Canvas query failed", {
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }

  // Fire-and-forget background recompute of a stale cached result.
  // force_async recomputes unconditionally, so kickoffs are rate-limited per
  // query: a canvas polling faster than the compute finishes must not stack
  // ClickHouse runs behind it.
  private revalidate(node: Record<string, unknown>): void {
    const key = JSON.stringify(node);
    const last = this.revalidatedAt.get(key);
    if (last != null && Date.now() - last < REVALIDATE_MIN_INTERVAL_MS) return;
    // Delete first so a re-set refreshes the key's Map position and the size
    // cap below always evicts the least recently refreshed query.
    this.revalidatedAt.delete(key);
    this.revalidatedAt.set(key, Date.now());
    // The map only ever holds queries some canvas is actively re-reading;
    // still, cap it so a long session can't grow it without bound.
    if (this.revalidatedAt.size > MAX_REVALIDATION_ENTRIES) {
      const oldest = this.revalidatedAt.keys().next().value;
      if (oldest !== undefined) this.revalidatedAt.delete(oldest);
    }
    void runQuery(this.authService, node, { refresh: "force_async" }).catch(
      (err) => {
        this.log.warn("Canvas background refresh failed", {
          error: err instanceof Error ? err.message : String(err),
        });
      },
    );
  }

  // The preferred data avenue: load a SAVED insight by short id and return its
  // STORED result from the insights endpoint (not a fresh /query/ run). The
  // canvas date picker's window rides along as the insight's date override, and
  // `variables` supplies the insight's SQL variables for this request.
  async loadInsight(input: CanvasLoadInsightInput): Promise<CanvasDataResult> {
    try {
      const insight = await fetchInsightByShortId(
        this.authService,
        input.shortId,
        { dateRange: input.dateRange, variables: input.variables },
      );
      assertVariablesApplied(
        input.variables,
        insight.resolvedVariables,
        input.shortId,
      );
      // Mirror the shape handling in `query`: a SQL insight returns rows (coerce a
      // bare scalar row to a 1-cell array); a trends-style insight returns SERIES
      // OBJECTS, which must pass through untouched (wrapping them reads every value
      // as 0).
      const isRows = insight.queryKind === "HogQLQuery";
      return boundedResult({
        columns: insight.columns,
        results: isRows
          ? insight.results.map((r) => (Array.isArray(r) ? r : [r]))
          : insight.results,
      });
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
