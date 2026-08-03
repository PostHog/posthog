import type {
  CanvasCaptureInput,
  CanvasDataQueryInput,
  CanvasLoadInsightInput,
} from "@posthog/core/canvas/freeformSchemas";
import type { QueryClient } from "@tanstack/react-query";
import { hostClient } from "../hostClient";

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
) {
  return queryClient.fetchQuery({
    queryKey: [CANVAS_QUERY_KEY, method, stableStringify(input)] as const,
    queryFn: run,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  });
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
): Promise<unknown> {
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
      return cachedRead(queryClient, "query", args, () =>
        hostClient().canvasData.query.mutate(args),
      );
    }
    case "loadInsight": {
      const input = payload as CanvasLoadInsightInput;
      if (!input?.shortId || typeof input.shortId !== "string") {
        throw new Error("ph.loadInsight(shortId) requires an insight short id");
      }
      const args = { shortId: input.shortId, dateRange: input.dateRange };
      return cachedRead(queryClient, "loadInsight", args, () =>
        hostClient().canvasData.loadInsight.mutate(args),
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
    case "run":
      // Named, server-stored insights land in Phase 3 (the live published tier).
      throw new Error("ph.run is not available yet (named queries: Phase 3)");
    default:
      throw new Error(`Unknown data method "${method}"`);
  }
}
