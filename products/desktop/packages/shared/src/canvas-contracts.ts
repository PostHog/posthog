import { z } from "zod";

// Contracts for the canvas application build pipeline (no I/O — pure schemas
// and validators shared by core, workspace-server, and the UI). A canvas is an
// arbitrary client-side browser application: its write format is a small
// multi-file source project, compiled by a build service into an immutable
// HTML/CSS/JS artifact that runs in the sandboxed canvas host.

export const CANVAS_SOURCE_SCHEMA_VERSION = 1;
export const CANVAS_ENTRY_HTML = "index.html";
// The single agent-editable file of a legacy (pre-build-service) canvas: the
// React component the runtime mounts. Mirrors the server's synthetic-project
// compatibility adapter.
export const CANVAS_COMPONENT_PATH = "src/canvas.tsx";

export const MAX_CANVAS_SOURCE_FILES = 64;
export const MAX_CANVAS_FILE_BYTES = 512 * 1024;
export const MAX_CANVAS_TOTAL_BYTES = 2 * 1024 * 1024;
export const MAX_CANVAS_ASSET_BYTES = 2 * 1024 * 1024;

export const canvasSourceAssetSchema = z.object({
  encoding: z.literal("base64"),
  contentType: z.enum([
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "font/woff",
    "font/woff2",
    "application/wasm",
    "application/octet-stream",
  ]),
  content: z.string(),
});
export type CanvasSourceAsset = z.infer<typeof canvasSourceAssetSchema>;

export const canvasCapabilitiesSchema = z.object({
  posthog: z.object({
    insights: z.array(z.string().min(1).max(128)).max(100),
    inlineQueries: z.boolean(),
    captureEvents: z.array(z.string().min(1).max(200)).max(100),
  }),
  network: z.object({
    origins: z.array(z.string().url().max(2_048)).max(20),
  }),
});
export type CanvasCapabilities = z.infer<typeof canvasCapabilitiesSchema>;

export const DEFAULT_CANVAS_CAPABILITIES: CanvasCapabilities = {
  posthog: { insights: [], inlineQueries: false, captureEvents: [] },
  network: { origins: [] },
};

/** A canvas's multi-file source project — the canonical write format. */
export const canvasSourceProjectSchema = z.object({
  schemaVersion: z.literal(CANVAS_SOURCE_SCHEMA_VERSION),
  /** Project files keyed by relative path (forward slashes, no '..'). */
  files: z.record(z.string(), z.string()),
  assets: z.record(z.string(), canvasSourceAssetSchema).optional(),
  entryHtml: z.literal(CANVAS_ENTRY_HTML),
  /** Exact-version dependencies, resolved by the build service. */
  dependencies: z.record(z.string(), z.string()),
  /** Version of the host-injected `ph` canvas SDK the project targets. */
  canvasSdkVersion: z.string(),
  capabilities: canvasCapabilitiesSchema.default(DEFAULT_CANVAS_CAPABILITIES),
});
export type CanvasSourceProject = z.infer<typeof canvasSourceProjectSchema>;

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

/** PostHog and network capabilities a built artifact declares and is held to. */
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

/** Immutable metadata for one published source version. */
export const canvasSourceVersionSchema = z.object({
  id: z.string(),
  parentVersionId: z.string().nullable(),
  taskId: z.string(),
  taskRunId: z.string(),
  sourceHash: z.string(),
  sourceObjectKey: z.string(),
  sourceSize: z.number().int().nonnegative(),
  prompt: z.string().optional(),
  createdAt: z.number(),
});
export type CanvasSourceVersion = z.infer<typeof canvasSourceVersionSchema>;

/** Lifecycle record of one build of a source version. */
export const canvasBuildSchema = z.object({
  id: z.string(),
  sourceVersionId: z.string(),
  status: canvasBuildStatusSchema,
  artifactObjectPrefix: z.string().optional(),
  integrity: z.string().optional(),
  diagnostics: z.array(canvasDiagnosticSchema),
  manifest: canvasArtifactManifestSchema.optional(),
});
export type CanvasBuild = z.infer<typeof canvasBuildSchema>;

const CANVAS_PATH_SEGMENT_RE = /^[A-Za-z0-9._@-]+$/;

/**
 * Why a project-relative file path is invalid, or null when it's fine.
 * Rejects absolute paths, backslashes, and empty/"."/".." segments so a
 * project can't address anything outside its own root.
 */
export function canvasSourcePathProblem(path: string): string | null {
  if (path === "" || path.startsWith("/") || path.includes("\\")) {
    return "file paths must be relative, non-empty, and use forward slashes";
  }
  for (const segment of path.split("/")) {
    if (segment === "" || segment === "." || segment === "..") {
      return "file paths must not contain empty, '.', or '..' segments";
    }
    if (!CANVAS_PATH_SEGMENT_RE.test(segment)) {
      return "file path segments may only contain letters, digits, '.', '_', '@', and '-'";
    }
  }
  return null;
}

/**
 * Structural validation of a candidate source project: schema shape, entry
 * presence, path safety, and file-count/size limits. Framework- and
 * policy-level checks (imports, dependency admission) belong to the build
 * service; this is the shared floor every adapter enforces identically.
 */
export function validateCanvasSourceProject(
  project: CanvasSourceProject,
): CanvasDiagnostic[] {
  const diagnostics: CanvasDiagnostic[] = [];

  const paths = Object.keys(project.files);
  if (paths.length > MAX_CANVAS_SOURCE_FILES) {
    diagnostics.push({
      severity: "error",
      code: "too_many_files",
      message: `a source project may contain at most ${MAX_CANVAS_SOURCE_FILES} files`,
    });
  }

  let totalBytes = 0;
  const encoder = new TextEncoder();
  for (const [path, content] of Object.entries(project.files)) {
    const problem = canvasSourcePathProblem(path);
    if (problem !== null) {
      diagnostics.push({
        severity: "error",
        code: "invalid_path",
        message: problem,
        path,
      });
      continue;
    }
    const size = encoder.encode(content).byteLength;
    totalBytes += size;
    if (size > MAX_CANVAS_FILE_BYTES) {
      diagnostics.push({
        severity: "error",
        code: "file_too_large",
        message: `file exceeds the ${MAX_CANVAS_FILE_BYTES / 1024} KB per-file limit`,
        path,
      });
    }
  }
  for (const [path, asset] of Object.entries(project.assets ?? {})) {
    const problem = canvasSourcePathProblem(path);
    if (problem !== null) {
      diagnostics.push({
        severity: "error",
        code: "invalid_path",
        message: problem,
        path,
      });
      continue;
    }
    if (
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
        asset.content,
      )
    ) {
      diagnostics.push({
        severity: "error",
        code: "invalid_asset",
        message: "asset content must be canonical base64",
        path,
      });
      continue;
    }
    const size = Math.floor((asset.content.length * 3) / 4);
    totalBytes += size;
    if (size > MAX_CANVAS_ASSET_BYTES) {
      diagnostics.push({
        severity: "error",
        code: "file_too_large",
        message: `asset exceeds the ${MAX_CANVAS_ASSET_BYTES / 1024} KB per-file limit`,
        path,
      });
    }
  }
  if (totalBytes > MAX_CANVAS_TOTAL_BYTES) {
    diagnostics.push({
      severity: "error",
      code: "project_too_large",
      message: `the source project exceeds the ${MAX_CANVAS_TOTAL_BYTES / 1024} KB total size limit`,
    });
  }

  if (!(project.entryHtml in project.files)) {
    diagnostics.push({
      severity: "error",
      code: "missing_entry",
      message: `the project must contain its entry file ${project.entryHtml}`,
      path: project.entryHtml,
    });
  }

  return diagnostics;
}

export function hasCanvasErrors(diagnostics: CanvasDiagnostic[]): boolean {
  return diagnostics.some((d) => d.severity === "error");
}
