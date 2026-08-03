import { z } from "zod";
import {
  CANVAS_ENTRY_HTML,
  type CanvasSourceProject,
  canvasArtifactManifestSchema,
  canvasDiagnosticSchema,
  canvasSourceProjectSchema,
} from "./canvas-contracts";

// The shared canvas build contract (no I/O). Local (workspace-server) and
// cloud build adapters implement the same request/result shapes and run the
// same contract fixtures, so a publish never produces different diagnostics
// than the preview that preceded it.

export const CANVAS_BUILD_CONTRACT_VERSION = 1;

/** One platform-supported dependency: pinned, pre-admitted, and resolvable. */
export interface CanvasDependencyAdmission {
  /** The exact version every canvas gets — canvases cannot pick their own. */
  version: string;
  /**
   * Browser module URL the preview import map resolves the bare specifier to.
   * Cloud builds may substitute self-hosted copies; the specifier and version
   * stay identical so source is portable across tiers.
   */
  importUrl: string;
  /** Extra import-map entries the package needs at runtime (subpath modules). */
  runtimeImports?: Record<string, string>;
}

const ESM_HOST = "https://esm.sh";
const QUILL_VERSION = "0.3.0-beta.18";

/**
 * Platform-supported dependencies with pinned versions and pre-admitted
 * status. Mirrors the legacy runtime's import whitelist (a drift test in
 * @posthog/core asserts the two stay aligned). npm packages outside this
 * registry go through guarded admission once the build service ships.
 */
export const CANVAS_PLATFORM_DEPENDENCIES: Record<
  string,
  CanvasDependencyAdmission
> = {
  react: {
    version: "19.0.0",
    importUrl: `${ESM_HOST}/react@19.0.0`,
    runtimeImports: {
      "react/jsx-runtime": `${ESM_HOST}/react@19.0.0/jsx-runtime`,
    },
  },
  "react-dom": {
    version: "19.0.0",
    importUrl: `${ESM_HOST}/react-dom@19.0.0?external=react`,
    runtimeImports: {
      "react-dom/client": `${ESM_HOST}/react-dom@19.0.0/client?external=react`,
    },
  },
  "@posthog/quill": {
    version: QUILL_VERSION,
    importUrl: `${ESM_HOST}/@posthog/quill@${QUILL_VERSION}?external=react,react-dom`,
  },
  recharts: {
    version: "2.15.0",
    importUrl: `${ESM_HOST}/recharts@2.15.0?external=react,react-dom`,
  },
  "lucide-react": {
    version: "1.21.0",
    importUrl: `${ESM_HOST}/lucide-react@1.21.0?external=react`,
  },
  dayjs: {
    version: "1.11.13",
    importUrl: `${ESM_HOST}/dayjs@1.11.13`,
  },
};

/** Import specifiers resolvable at runtime (package roots + subpath modules). */
export function canvasRuntimeImportMap(
  dependencies: Record<string, string>,
): Record<string, string> {
  const imports: Record<string, string> = {};
  for (const name of Object.keys(dependencies)) {
    const admission = CANVAS_PLATFORM_DEPENDENCIES[name];
    if (!admission) continue;
    imports[name] = admission.importUrl;
    Object.assign(imports, admission.runtimeImports);
  }
  return imports;
}

// Emitted-artifact budgets, enforced by every adapter's output scan. The
// per-file budget is deliberately below the source-project total so a bundle
// that concatenates many modules into one chunk still has a ceiling.
export const MAX_CANVAS_ARTIFACT_FILE_BYTES = 1024 * 1024;
export const MAX_CANVAS_ARTIFACT_TOTAL_BYTES = 8 * 1024 * 1024;
export const CANVAS_BUILD_TIMEOUT_MS = 30_000;

export const canvasBuildModeSchema = z.enum(["validate", "publish"]);
export type CanvasBuildMode = z.infer<typeof canvasBuildModeSchema>;

export const canvasBuildRequestSchema = z.object({
  /** Target canvas, when known (previews for an unsaved draft may omit it). */
  canvasId: z.string().optional(),
  /** Source version the project was read at, for attribution/conflicts. */
  sourceVersionId: z.string().optional(),
  project: canvasSourceProjectSchema,
  /**
   * "validate" returns diagnostics and a short-lived preview artifact;
   * "publish" additionally makes the artifact eligible for upload. Local
   * adapters only ever validate — cloud builds are authoritative for
   * publication.
   */
  mode: canvasBuildModeSchema,
});
export type CanvasBuildRequest = z.infer<typeof canvasBuildRequestSchema>;

/** One emitted artifact file. Text content (HTML/JS/CSS) in phase 2. */
export const canvasArtifactFileSchema = z.object({
  path: z.string(),
  content: z.string(),
  /** Hex SHA-256 of the UTF-8 content. */
  contentHash: z.string(),
  sizeBytes: z.number().int().nonnegative(),
});
export type CanvasArtifactFile = z.infer<typeof canvasArtifactFileSchema>;

export const canvasBuildResultSchema = z.object({
  contractVersion: z.literal(CANVAS_BUILD_CONTRACT_VERSION),
  status: z.enum(["ready", "failed"]),
  diagnostics: z.array(canvasDiagnosticSchema),
  /** Present when status is "ready". */
  manifest: canvasArtifactManifestSchema.optional(),
  /** Emitted files, entry first. Present when status is "ready". */
  files: z.array(canvasArtifactFileSchema).optional(),
});
export type CanvasBuildResult = z.infer<typeof canvasBuildResultSchema>;

/** The one build boundary: source in, artifact + diagnostics out — never shell commands. */
export interface CanvasBuildAdapter {
  buildCanvas(request: CanvasBuildRequest): Promise<CanvasBuildResult>;
}

// ── Neutral web-project starter ─────────────────────────────────────────────
// New canvases start from one intentionally small project. The entry stays
// vanilla TypeScript; importing React (or anything else platform-supported)
// is an edit, not a different canvas kind.

export const CANVAS_STARTER_INDEX_HTML = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="/src/style.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
`;

export const CANVAS_STARTER_MAIN_TS = `const root = document.getElementById("root");

if (root) {
  const heading = document.createElement("h1");
  heading.textContent = "New canvas";
  const hint = document.createElement("p");
  hint.textContent = "Edit src/main.ts to build this canvas.";
  root.append(heading, hint);
}

export {};
`;

export const CANVAS_STARTER_STYLE_CSS = `:root {
  color-scheme: light dark;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--foreground, #0d0d0d);
  background: var(--background, #ffffff);
}

#root {
  padding: 24px;
}
`;

export function createCanvasStarterProject(): CanvasSourceProject {
  return {
    schemaVersion: 1,
    files: {
      [CANVAS_ENTRY_HTML]: CANVAS_STARTER_INDEX_HTML,
      "src/main.ts": CANVAS_STARTER_MAIN_TS,
      "src/style.css": CANVAS_STARTER_STYLE_CSS,
    },
    entryHtml: CANVAS_ENTRY_HTML,
    dependencies: Object.fromEntries(
      Object.entries(CANVAS_PLATFORM_DEPENDENCIES).map(([name, admission]) => [
        name,
        admission.version,
      ]),
    ),
    canvasSdkVersion: "0.1.0",
    capabilities: {
      posthog: { insights: [], inlineQueries: false, captureEvents: [] },
      network: { origins: [] },
    },
  };
}
