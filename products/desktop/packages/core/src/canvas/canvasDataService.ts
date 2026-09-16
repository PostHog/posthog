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

const FALLBACK_DISTINCT_ID = "freeform-canvas";
const MAX_CANVAS_RESULT_ROWS = 1_000;
const MAX_CANVAS_RESULT_BYTES = 2 * 1024 * 1024;
const REVALIDATE_MIN_INTERVAL_MS = 30_000;
const MAX_REVALIDATION_ENTRIES = 512;

const utf8Encoder = new TextEncoder();

function exceedsByteLimit(json: string): boolean {
  if (json.length > MAX_CANVAS_RESULT_BYTES) return true;
  if (json.length * 3 <= MAX_CANVAS_RESULT_BYTES) return false;
  return utf8Encoder.encode(json).byteLength > MAX_CANVAS_RESULT_BYTES;
}

function normalizeHogQLRows(results: unknown[]): unknown[] {
  return results.map((result) => (Array.isArray(result) ? result : [result]));
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

function sameVariableValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

// Reject ignored overrides because the insight can return plausible saved defaults.
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

@injectable()
export class CanvasDataService {
  private readonly log: ScopedLogger;
  private readonly projectTokens = new Map<number, string>();
  private userDistinctId: string | undefined;
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
      const isTyped = input.query != null;
      const node = isTyped
        ? (input.query as Record<string, unknown>)
        : { kind: "HogQLQuery", query: input.hogql as string };
      // Typed results are series objects. Wrapping them makes their values read as zero.
      const shaped = (results: unknown[]): unknown[] =>
        isTyped ? results : normalizeHogQLRows(results);

      if (input.refresh != null) {
        // A failed cache probe must not block the query runner.
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

  private revalidate(node: Record<string, unknown>): void {
    const key = JSON.stringify(node);
    const last = this.revalidatedAt.get(key);
    if (last != null && Date.now() - last < REVALIDATE_MIN_INTERVAL_MS) return;
    // Re-insert the key so the size cap removes the least recently refreshed query.
    this.revalidatedAt.delete(key);
    this.revalidatedAt.set(key, Date.now());
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
      const isRows = insight.queryKind === "HogQLQuery";
      return boundedResult({
        columns: insight.columns,
        results: isRows ? normalizeHogQLRows(insight.results) : insight.results,
      });
    } catch (err) {
      this.log.warn("Canvas loadInsight failed", {
        shortId: input.shortId,
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }
  }

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

  async capture(input: CanvasCaptureInput): Promise<CanvasCaptureResult> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) {
      throw new Error("No PostHog project selected");
    }

    const apiKey = await this.getProjectToken(apiHost, projectId);
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

  private async getUserDistinctId(): Promise<string | undefined> {
    if (this.userDistinctId !== undefined) return this.userDistinctId;
    const user = await fetchCurrentUser(this.authService);
    this.userDistinctId = user?.distinctId;
    return this.userDistinctId;
  }
}
