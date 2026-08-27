import { isSafePostHogUrl } from "@posthog/shared";
import { z } from "zod";
import { textCommentAnchorDataSchema } from "../comments/anchors";

// The template id for freeform-React canvases. Stored on a canvas's meta so the
// generation path can resolve the right system prompt.
export const FREEFORM_TEMPLATE_ID = "freeform";

// ---------------------------------------------------------------------------
// Canvas data avenue: the host-side query the postMessage `ph.query` shim calls.
// Routed through PostHog's cached query runner (the same avenue insights use, so
// caching + cold-boot are handled), never a bare uncached /query (the token is
// injected host-side; the iframe only sees this shape).
//
// Two shapes (the agent picks per metric; see the canvas templates skill):
//   • `query` — a TYPED query node (`{ kind: "TrendsQuery" | "FunnelsQuery" |
//     "HogQLQuery" | … }`). PREFERRED: the product's own query runners compute it,
//     so the numbers match the PostHog UI (sessionization, unique users, bounce
//     rate, breakdowns, math) and the typed `dateRange` handles windows correctly.
//   • `hogql` — an inline HogQL string (wrapped server-side as a HogQLQuery).
//     Escape hatch for shapes a typed node can't express; the agent owns the SQL.
// Exactly one must be present. Edit mode allows both; view/published mode (Phase 3)
// rejects inline and requires a named, server-stored insight via `run`.
// ---------------------------------------------------------------------------
export const canvasDataQueryInput = z
  .object({
    // A typed query node passed straight to the query runner. Opaque here (the
    // node schemas are large + product-owned); validated by the API on execution.
    query: z.record(z.string().max(256), z.unknown()).optional(),
    // Inline HogQL string (the escape hatch). Server wraps it as a HogQLQuery.
    hogql: z.string().min(1).max(20_000).optional(),
    // Reserved for bound parameters (Phase 3 named queries). Edit mode ignores it.
    params: z.record(z.string().max(128), z.unknown()).optional(),
    refresh: z.number().int().min(30).max(86_400).optional(),
  })
  .refine((v) => v.query != null || v.hogql != null, {
    message: "ph.query requires a query node or a HogQL string",
  });
export type CanvasDataQueryInput = z.infer<typeof canvasDataQueryInput>;

export const canvasDataResultSchema = z.object({
  columns: z.array(z.string()),
  // The result rows. SHAPE DEPENDS ON THE QUERY KIND (true for both `ph.query`
  // and `ph.loadInsight`):
  //   • HogQLQuery / SQL insight → an array of ROWS, each row an array of cell
  //     values aligned to `columns` (e.g. `[[123], [456]]`).
  //   • Typed nodes / trends-style insight → an array of SERIES OBJECTS as PostHog
  //     returns them — `{ data: number[], labels: string[], days: string[],
  //     count, aggregated_value, compare_label, … }`. NOT rows-of-cells; passed
  //     through untouched so the canvas reads the native trends shape.
  // Hence `unknown` per element rather than `unknown[]`.
  results: z.array(z.unknown()),
});
export type CanvasDataResult = z.infer<typeof canvasDataResultSchema>;

// ---------------------------------------------------------------------------
// Load-insight avenue: the host-side fetch behind the `ph.loadInsight` shim. The
// canvas references a SAVED, validated PostHog insight by `short_id` and the host
// returns its STORED result from the insights endpoint (not a fresh `/query/`
// run). This is the preferred data path — every metric is a proven saved insight.
// `dateRange` (the canvas date picker's window) re-scopes the insight for this
// request via `filters_override`. The result is the same `{ columns, results }`
// shape as `ph.query`.
//
// `variables` supplies per-request values for a SQL insight's HogQL variables (the
// `{variables.code_name}` placeholders), forwarded as `variables_override`. This is
// what lets ONE saved insight serve a whole board — a per-product revenue insight
// rendered once per product — instead of only ever resolving its saved defaults. A
// SQL variable is a SEPARATE axis from `dateRange`: an insight whose month comes
// from a `{variables.month}` placeholder is driven through `variables`, and no
// `dateRange` will ever reach it.
// ---------------------------------------------------------------------------
export const canvasLoadInsightInput = z.object({
  shortId: z.string().min(1).max(128),
  dateRange: z
    .object({ date_from: z.string().nullish(), date_to: z.string().nullish() })
    .optional(),
  // Keyed by the variable's `code_name`, not its uuid — the host resolves ids
  // server-side, so canvas code never carries a variable uuid.
  variables: z.record(z.string().min(1).max(128), z.unknown()).optional(),
  refresh: z.number().int().min(30).max(86_400).optional(),
});
export type CanvasLoadInsightInput = z.infer<typeof canvasLoadInsightInput>;

// Capture (write) avenue behind the `ph.capture` shim. The host sends the event
// to the project using its PUBLIC project key (phc_…, safe to be client-side) —
// the private read token still never enters the iframe. `distinctId` is who the
// event is attributed to; defaults host-side when omitted.
export const canvasCaptureInput = z.object({
  event: z.string().min(1).max(200),
  distinctId: z.string().min(1).max(200).optional(),
  properties: z.record(z.string(), z.unknown()).optional(),
});
export type CanvasCaptureInput = z.infer<typeof canvasCaptureInput>;

export const canvasCaptureResultSchema = z.object({ ok: z.boolean() });
export type CanvasCaptureResult = z.infer<typeof canvasCaptureResultSchema>;

export const canvasAgentRequestInputSchema = z.object({
  prompt: z.string().min(1).max(10_000),
});
export type CanvasAgentRequestInput = z.infer<
  typeof canvasAgentRequestInputSchema
>;

export const canvasAgentRequestResultSchema = z.object({
  requestOutcome: z.enum(["signaled", "new_run", "already_queued", "reported"]),
  taskId: z.string().min(1),
});
export type CanvasAgentRequestResult = z.infer<
  typeof canvasAgentRequestResultSchema
>;

// What the host hands the UI to bootstrap in-iframe analytics/replay. The
// public capture key + the signed-in user's distinct_id; the private token is
// never included. The UI forwards this into the iframe `init` frame.
export const canvasCaptureConfigSchema = z.object({
  apiHost: z.string(),
  publicKey: z.string(),
  distinctId: z.string().optional(),
});
export type CanvasCaptureConfig = z.infer<typeof canvasCaptureConfigSchema>;

// ---------------------------------------------------------------------------
// Host <-> iframe postMessage protocol (Q10/Q11). The canvas runs in a
// null-origin sandboxed iframe, so it CANNOT share JS objects with the host —
// every interaction is a structured-clone message. The real PostHog token never
// crosses this boundary: the iframe sends a data-request; the host runs the
// authenticated call and returns only the result.
// ---------------------------------------------------------------------------

// Stamped on every frame so a page hosting multiple canvas iframes (or other
// postMessage traffic) can route unambiguously.
const CANVAS_CHANNEL = "posthog-canvas" as const;
export const CANVAS_MESSAGE_CHANNEL = CANVAS_CHANNEL;

// Analytics bootstrap config handed to the iframe so posthog-js can run INSIDE
// it (the only way session replay records the app's DOM). Only the PUBLIC
// capture key crosses — never the private read token. `distinctId` seeds
// attribution (the signed-in user in edit; omitted for anonymous shared
// viewers, who get an auto-generated id). `persist` is false on a null-origin
// sandbox (no storage) → memory session; true on the usercontent origin.
export const canvasAnalyticsConfigSchema = z.object({
  apiHost: z.string(),
  publicKey: z.string(),
  distinctId: z.string().optional(),
  persist: z.boolean(),
});
export type CanvasAnalyticsConfig = z.infer<typeof canvasAnalyticsConfigSchema>;

// The light/dark appearance the host wants the canvas to render in. Mirrors the
// host's resolved theme (system preference already collapsed to light/dark).
// The iframe toggles a `.dark` class on its document root from this — the same
// mechanism the main app uses — so Quill's CSS tokens and `dark:` utilities flip.
export const canvasThemeSchema = z.enum(["light", "dark"]);
export type CanvasTheme = z.infer<typeof canvasThemeSchema>;

const canvasTextSelectionDataSchema = textCommentAnchorDataSchema.extend({
  rect: z.object({
    top: z.number().finite(),
    right: z.number().finite(),
    bottom: z.number().finite(),
    left: z.number().finite(),
  }),
});
export const canvasTextSelectionSchema = canvasTextSelectionDataSchema.refine(
  ({ start, end }) => end > start,
);
export type CanvasTextSelection = z.infer<typeof canvasTextSelectionSchema>;

export const canvasCommentHighlightSchema = z.object({
  id: z.string().min(1).max(128),
  active: z.boolean(),
  anchor: textCommentAnchorDataSchema.refine(({ start, end }) => end > start),
});
export type CanvasCommentHighlight = z.infer<
  typeof canvasCommentHighlightSchema
>;

export const MAX_CANVAS_COMMENT_HIGHLIGHTS = 500;
export const MAX_CANVAS_COMMENT_HIGHLIGHT_TEXT_LENGTH = 100_000;

export function limitCanvasCommentHighlights(
  highlights: CanvasCommentHighlight[],
): CanvasCommentHighlight[] {
  const limited: CanvasCommentHighlight[] = [];
  let textLength = 0;
  for (const highlight of highlights) {
    const nextTextLength =
      textLength +
      highlight.anchor.quote.length +
      highlight.anchor.prefix.length +
      highlight.anchor.suffix.length;
    if (
      limited.length >= MAX_CANVAS_COMMENT_HIGHLIGHTS ||
      nextTextLength > MAX_CANVAS_COMMENT_HIGHLIGHT_TEXT_LENGTH
    ) {
      break;
    }
    limited.push(highlight);
    textLength = nextTextLength;
  }
  return limited;
}

// host -> iframe
export const hostToCanvasMessageSchema = z.discriminatedUnion("type", [
  // First frame: hand the iframe its source. The iframe does not fetch its own
  // code; the host injects it so the host controls what runs. Only the srcDoc
  // authoring sandbox takes an `init` — a published canvas is a built artifact
  // that boots itself and only receives the frames below.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("init"),
    code: z.string(),
    // Present when analytics/replay should run in the iframe. Absent = no capture.
    analytics: canvasAnalyticsConfigSchema.optional(),
    // The appearance to render in. Carried on `init` so the first render is
    // already correct; live theme changes use the `set-theme` frame below
    // (which re-themes without remounting). Absent = light.
    theme: canvasThemeSchema.optional(),
    highlights: z
      .array(canvasCommentHighlightSchema)
      .max(MAX_CANVAS_COMMENT_HIGHLIGHTS)
      .optional(),
  }),
  // Live theme change: re-apply light/dark WITHOUT remounting the app. Sent on
  // its own (not folded into `init`) so toggling the host theme — or an OS
  // dark/light flip under the "system" preference — doesn't reset canvas state.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("set-theme"),
    theme: canvasThemeSchema,
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("set-comment-highlights"),
    highlights: z
      .array(canvasCommentHighlightSchema)
      .max(MAX_CANVAS_COMMENT_HIGHLIGHTS),
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("clear-text-selection"),
  }),
  // Reply to a data-request, correlated by `id`.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("data-response"),
    id: z.string(),
    ok: z.boolean(),
    result: z.unknown().optional(),
    error: z.string().optional(),
  }),
]);
export type HostToCanvasMessage = z.infer<typeof hostToCanvasMessageSchema>;

// The ONLY navigations a canvas may request of the host. The canvas runs
// untrusted code in a null-origin iframe, so this nested union IS the security
// allowlist: there is no free-form path/route field, only these four targets.
// `channelId` is intentionally absent — the host supplies it from the loaded
// record so the iframe can never pick the channel, only which task/dashboard.
export const canvasNavIntentSchema = z.discriminatedUnion("target", [
  z.object({ target: z.literal("task"), taskId: z.string().min(1) }),
  z.object({ target: z.literal("new-task") }),
  z.object({ target: z.literal("canvas"), dashboardId: z.string().min(1) }),
  z.object({ target: z.literal("new-canvas") }),
]);
export type CanvasNavIntent = z.infer<typeof canvasNavIntentSchema>;

// iframe -> host
export const canvasToHostMessageSchema = z.discriminatedUnion("type", [
  // Iframe runtime is mounted and ready to receive `init`.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("ready"),
  }),
  // A data call from canvas code. `method` is the shim method (e.g. "run" for a
  // named query, "query" for inline HogQL in edit mode). The host validates +
  // executes; nothing here carries credentials.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("data-request"),
    id: z.string().min(1).max(128),
    method: z.enum([
      "query",
      "loadInsight",
      "capture",
      "run",
      "stateGet",
      "stateSet",
      "stateList",
      "actionInvoke",
      "agentRequest",
    ]),
    payload: z.unknown(),
  }),
  // A runtime/compile error from inside the iframe, surfaced so the host can
  // show a non-blocking notice and feed it back to the agent for self-repair
  // (Q7 error-recovery loop).
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("error"),
    message: z.string().max(10_000),
    stack: z.string().max(50_000).optional(),
  }),
  // The canvas rendered successfully (clears any prior error state).
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("rendered"),
  }),
  // A request to navigate the host app. Fire-and-forget (no id/response). The
  // `nav` payload is the allowlist above — the host drops anything that doesn't
  // parse, so the iframe can only reach the four sanctioned destinations.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("navigate"),
    nav: canvasNavIntentSchema,
  }),
  // Open a URL outside the sandbox. The PostHog-only https allowlist is part
  // of the schema, so no consumer can forward an unvalidated URL.
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("open-external"),
    url: z.string().refine(isSafePostHogUrl),
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("text-selection"),
    selection: canvasTextSelectionSchema,
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("text-selection-cleared"),
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("comment-activate"),
    id: z.string().min(1).max(128),
  }),
  z.object({
    channel: z.literal(CANVAS_CHANNEL),
    type: z.literal("keydown"),
    key: z.string().min(1).max(32),
    code: z.string().max(32),
    metaKey: z.boolean(),
    ctrlKey: z.boolean(),
    shiftKey: z.boolean(),
    altKey: z.boolean(),
  }),
]);
export type CanvasToHostMessage = z.infer<typeof canvasToHostMessageSchema>;
