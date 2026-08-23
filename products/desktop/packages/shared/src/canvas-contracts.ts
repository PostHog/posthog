import { z } from "zod";

// Contracts for the canvas application build pipeline (no I/O — pure schemas
// shared by core and the UI; the build service itself lives server-side). A
// canvas is an arbitrary client-side browser application: its write format is
// a small multi-file source project, compiled by a build service into an
// immutable HTML/CSS/JS artifact that runs in the sandboxed canvas host.

export const CANVAS_SOURCE_SCHEMA_VERSION = 1;
export const CANVAS_ENTRY_HTML = "index.html";
// The single agent-editable file of a legacy (pre-build-service) canvas: the
// React component the runtime mounts. Mirrors the server's synthetic-project
// compatibility adapter.
export const CANVAS_COMPONENT_PATH = "src/canvas.tsx";

// Every field is defaulted: the builder freezes project.capabilities into the
// manifest VERBATIM, and a project declares only the capabilities it uses — a
// required field here makes the whole build record unparseable client-side,
// which reads as "this canvas has no build". Absent means deny at runtime, so
// defaulting is the fail-closed direction.
export const canvasCapabilitiesSchema = z.object({
  posthog: z
    .object({
      insights: z.array(z.string().min(1).max(128)).max(100).default([]),
      inlineQueries: z.boolean().default(false),
      captureEvents: z.array(z.string().min(1).max(200)).max(100).default([]),
      state: z
        .array(z.enum(["user", "shared"]))
        .max(2)
        .default([]),
      actions: z.array(z.string().min(1).max(64)).max(32).default([]),
      agentRequests: z.boolean().default(false),
    })
    .default({
      insights: [],
      inlineQueries: false,
      captureEvents: [],
      state: [],
      actions: [],
      agentRequests: false,
    }),
  network: z
    .object({
      origins: z.array(z.string().url().max(2_048)).max(20).default([]),
    })
    .default({ origins: [] }),
});
export type CanvasCapabilities = z.infer<typeof canvasCapabilitiesSchema>;

export const canvasDiagnosticSeveritySchema = z.enum(["error", "warning"]);
export type CanvasDiagnosticSeverity = z.infer<
  typeof canvasDiagnosticSeveritySchema
>;

/** One structured validation/build diagnostic for a canvas source project. */
export const canvasDiagnosticSchema = z.object({
  /** "error" blocks publishing; "warning" is advisory. */
  severity: canvasDiagnosticSeveritySchema,
  /** Stable machine-readable code, e.g. "import_not_allowed". */
  code: z.string(),
  message: z.string(),
  /** Project-relative path the diagnostic points at, when file-specific. */
  path: z.string().optional(),
  /** 1-based line within `path`, when line-specific. */
  line: z.number().int().positive().optional(),
});
export type CanvasDiagnostic = z.infer<typeof canvasDiagnosticSchema>;

export const canvasBuildStatusSchema = z.enum([
  "queued",
  "building",
  "ready",
  "failed",
]);
export type CanvasBuildStatus = z.infer<typeof canvasBuildStatusSchema>;

/** One emitted asset of a built artifact. */
export const canvasArtifactAssetSchema = z.object({
  path: z.string(),
  contentHash: z.string(),
  sizeBytes: z.number().int().nonnegative(),
});
export type CanvasArtifactAsset = z.infer<typeof canvasArtifactAssetSchema>;

/** Manifest frozen into a build: entry, assets, versions, and capabilities. */
export const canvasArtifactManifestSchema = z.object({
  entryHtml: z.string(),
  assets: z.array(canvasArtifactAssetSchema),
  dependencies: z.record(z.string(), z.string()),
  canvasSdkVersion: z.string(),
  capabilities: canvasCapabilitiesSchema,
});
export type CanvasArtifactManifest = z.infer<
  typeof canvasArtifactManifestSchema
>;
