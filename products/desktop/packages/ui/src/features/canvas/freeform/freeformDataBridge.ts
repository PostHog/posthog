import type {
  CanvasCaptureInput,
  CanvasDataQueryInput,
  CanvasLoadInsightInput,
} from "@posthog/core/canvas/freeformSchemas";
import type { QueryClient } from "@tanstack/react-query";
import { hostClient } from "../hostClient";

// Capability gating (assertCanvasCapability) lives in
// @posthog/core/canvas/canvasCapabilities — it's a pure business rule, not a
// transport concern; this file owns only the request routing + read cache.

// Namespace for every cached canvas read.
export const CANVAS_QUERY_KEY = "canvasData/read";

// Deterministic stringify for cache keys: object keys are emitted in sorted order
// at every depth so two reads that differ only by key order share a cache entry.
// `undefined` and non-finite numbers get distinct tokens — JSON.stringify would
// collapse them all to `null`, so `[undefined]` and `[null]` would wrongly share a
// cache entry (and thus a result).
function stableStringify(value: unknown): string {
  if (value === undefined) return "undef";
  if (value === null) return "null";
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : `num:${String(value)}`;
  }
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    // Positional: keep `undefined` holes distinct from `null`.
    return `[${value.map(stableStringify).join(",")}]`;
  }
  // Object: an absent key and an explicit `undefined` value serialize the same
  // over tRPC, so dropping undefined-valued keys keeps the key in sync with what
  // the server actually receives.
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`);
  return `{${entries.join(",")}}`;
}

// Reads go through the shared QueryClient cache: an iframe re-boot, a canvas
// code-swap, and live edit re-renders all resolve a repeated read from cache
// instead of re-hitting ClickHouse, and concurrent identical reads dedupe. The key
// is content-based (no canvas id) so identical reads across canvases — and across a
// card preview and its full view — share one entry.
function cachedRead<T>(
  queryClient: QueryClient,
  method: string,
  input: unknown,
  run: () => Promise<T>,
  refreshSeconds?: number,
) {
  return queryClient.fetchQuery({
    queryKey: [CANVAS_QUERY_KEY, method, stableStringify(input)] as const,
    queryFn: run,
    staleTime: (refreshSeconds ?? 5 * 60) * 1_000,
    // At least the refresh interval, or GC would evict an inactive entry
    // before it goes stale and force an early backend re-read.
    gcTime: Math.max(refreshSeconds ?? 5 * 60, 10 * 60) * 1_000,
  });
}

function refreshSeconds(value: unknown): number | undefined {
  if (value === undefined) return undefined;
  if (
    !Number.isInteger(value) ||
    (value as number) < 30 ||
    (value as number) > 86_400
  ) {
    throw new Error("refresh must be an integer between 30 and 86400 seconds");
  }
  return value as number;
}

// Resolves a `ph.*` data-request from a freeform canvas (edit mode). The host
// injects the PostHog token; the iframe only ever sees the result. The QueryClient
// is passed in by the calling component (via useQueryClient) rather than resolved
// here, so this stays a pure function with no host/DI coupling. View/published mode
// (Phase 3) swaps this for a share-token proxy that accepts only `run` of an
// allowlisted named insight.
export async function handleFreeformDataRequest(
  method: string,
  payload: unknown,
  queryClient: QueryClient,
  // State and actions are canvas-scoped, unlike the content-keyed reads above,
  // so the caller passes the canvas identity in.
  context?: { dashboardId?: string },
): Promise<unknown> {
  const requireDashboardId = (): string => {
    if (!context?.dashboardId) {
      throw new Error(`${method} requires a canvas context`);
    }
    return context.dashboardId;
  };
  switch (method) {
    case "query": {
      const input = payload as CanvasDataQueryInput;
      const hasQuery = input?.query != null && typeof input.query === "object";
      const hasHogql =
        typeof input?.hogql === "string" && input.hogql.length > 0;
      if (!hasQuery && !hasHogql) {
        throw new Error(
          "ph.query requires a typed query node or a HogQL string",
        );
      }
      const args = {
        query: input.query,
        hogql: input.hogql,
        params: input.params,
      };
      return cachedRead(
        queryClient,
        "query",
        args,
        () => hostClient().canvasData.query.mutate(args),
        refreshSeconds(input.refresh),
      );
    }
    case "loadInsight": {
      const input = payload as CanvasLoadInsightInput;
      if (!input?.shortId || typeof input.shortId !== "string") {
        throw new Error("ph.loadInsight(shortId) requires an insight short id");
      }
      // `variables` is part of the cache key, not just the request: the same insight
      // loaded for two different products is two different results, and omitting it
      // here would serve the first product's numbers for every one of them.
      const args = {
        shortId: input.shortId,
        dateRange: input.dateRange,
        variables: input.variables,
      };
      return cachedRead(
        queryClient,
        "loadInsight",
        args,
        () => hostClient().canvasData.loadInsight.mutate(args),
        refreshSeconds(input.refresh),
      );
    }
    case "capture": {
      const input = payload as CanvasCaptureInput;
      if (!input?.event || typeof input.event !== "string") {
        throw new Error("ph.capture(event) requires an event name");
      }
      // A side-effect, never cached.
      return hostClient().canvasData.capture.mutate({
        event: input.event,
        distinctId: input.distinctId,
        properties: input.properties,
      });
    }
    case "stateGet": {
      const input = payload as { key?: string; scope?: "user" | "shared" };
      if (!input?.key || typeof input.key !== "string") {
        throw new Error("ph.state.get(key) requires a key");
      }
      // Never cached: state is the canvas's live memory, and a stale read
      // would undo the write the canvas just made.
      const entries = await hostClient().dashboards.listState.query({
        id: requireDashboardId(),
        scope: input.scope ?? "user",
      });
      return entries.find((entry) => entry.key === input.key)?.value ?? null;
    }
    case "stateSet": {
      const input = payload as {
        key?: string;
        value?: unknown;
        scope?: "user" | "shared";
      };
      if (!input?.key || typeof input.key !== "string") {
        throw new Error("ph.state.set(key, value) requires a key");
      }
      await hostClient().dashboards.setState.mutate({
        id: requireDashboardId(),
        scope: input.scope ?? "user",
        key: input.key,
        value: input.value ?? null,
      });
      return { ok: true };
    }
    case "stateList": {
      const input = payload as { scope?: "user" | "shared" };
      return hostClient().dashboards.listState.query({
        id: requireDashboardId(),
        scope: input?.scope,
      });
    }
    case "actionInvoke": {
      const input = payload as {
        verb?: string;
        payload?: Record<string, unknown>;
      };
      if (!input?.verb || typeof input.verb !== "string") {
        throw new Error("ph.actions.invoke(verb, payload) requires a verb");
      }
      // A write into PostHog, never cached.
      return hostClient().dashboards.invokeAction.mutate({
        id: requireDashboardId(),
        verb: input.verb,
        payload: input.payload ?? {},
      });
    }
    case "run":
      // Named, server-stored insights land in Phase 3 (the live published tier).
      throw new Error("ph.run is not available yet (named queries: Phase 3)");
    default:
      throw new Error(`Unknown data method "${method}"`);
  }
}
