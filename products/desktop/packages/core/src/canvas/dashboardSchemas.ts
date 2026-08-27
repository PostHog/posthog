import {
  CANVAS_PLATFORM_MANIFEST,
  canvasBuildStatusSchema,
} from "@posthog/shared";
import { z } from "zod";
import { canvasAgentRequestInputSchema } from "./freeformSchemas";
import { componentMetaSchema } from "./gridLayoutSchemas";

// A canvas record from the PostHog canvases API, normalized to camelCase and
// epoch-ms timestamps. Source code and version history are NOT part of the
// record — they live behind the source/versions endpoints, and the rendered
// output behind the build lifecycle.
export const canvasKindSchema = z.enum(["freeform", "grid", "component"]);
export type CanvasKind = z.infer<typeof canvasKindSchema>;

export const dashboardRecordSchema = z.object({
  id: z.string(),
  // The backend channel (task channel UUID) this canvas belongs to.
  channelId: z.string(),
  name: z.string(),
  // freeform: a standalone app. component: a reusable widget grids place.
  // grid: a composition of components (its source is a layout document).
  kind: canvasKindSchema.default("freeform"),
  // Short prose describing the canvas; for components, the store-search text.
  description: z.string().default(""),
  // For components: the head version's placement contract (size, configSchema).
  componentMeta: componentMetaSchema.nullish(),
  templateId: z.string().default("freeform"),
  // The live author-written context (markdown) passed to the agent.
  context: z.string().default(""),
  // Id of the task currently generating this canvas (freeform gen runs as a
  // dedicated task, like CONTEXT.md). null/absent = no generation in flight.
  generationTaskId: z.string().nullish(),
  // Display name of the creator (from the backend's created_by user).
  createdBy: z.string().optional(),
  createdByUuid: z.string().optional(),
  createdAt: z.number(),
  updatedAt: z.number(),
  // Epoch ms the canvas was pinned to its channel; absent = not pinned.
  pinnedAt: z.number().optional(),
  // Head source version — pass as expected_current_version_id when publishing.
  currentVersionId: z.string().nullish(),
  // The live (last successful, still-eligible) build.
  publishedBuildId: z.string().nullish(),
});
export type DashboardRecord = z.infer<typeof dashboardRecordSchema>;

// One entry of a canvas's version history (metadata only — a version's files
// are fetched via source({versionId})).
export const canvasVersionSchema = z.object({
  id: z.string(),
  parentVersionId: z.string().nullish(),
  prompt: z.string().nullish(),
  taskId: z.string().nullish(),
  createdBy: z.string().optional(),
  createdAt: z.number(),
});
export type CanvasVersion = z.infer<typeof canvasVersionSchema>;

// A staged draft version and the status of its latest build. Drafts are kept
// out of the published version history (canvasVersionSchema); they are surfaced
// separately so the head/live timeline stays clean.
export const canvasDraftSchema = z.object({
  versionId: z.string(),
  prompt: z.string().nullish(),
  createdBy: z.string().optional(),
  createdAt: z.number(),
  buildStatus: canvasBuildStatusSchema.nullish(),
  buildId: z.string().nullish(),
});
export type CanvasDraft = z.infer<typeof canvasDraftSchema>;

// A canvas source project — the multi-file write format the agent publishes.
export const canvasSourceProjectSchema = z.object({
  schemaVersion: z.number(),
  files: z.record(z.string(), z.string()),
  entryHtml: z.string(),
  dependencies: z.record(z.string(), z.string()).default({}),
  canvasSdkVersion: z
    .string()
    .default(CANVAS_PLATFORM_MANIFEST.canvasSdkVersion),
  assets: z.record(z.string(), z.unknown()).optional(),
  capabilities: z.unknown().optional(),
});
export type CanvasSourceProject = z.infer<typeof canvasSourceProjectSchema>;

export const canvasSourceSchema = z.object({
  project: canvasSourceProjectSchema,
  // The canvas's head version id (regardless of which version was read).
  currentVersionId: z.string().nullish(),
});
export type CanvasSource = z.infer<typeof canvasSourceSchema>;

export const listDashboardsInput = z.object({ channelId: z.string().min(1) });

// The component store: component-kind canvases across every channel visible to
// the caller, optionally narrowed by a name/description search.
export const listComponentsInput = z.object({
  search: z.string().optional(),
});

export const createDashboardInput = z.object({
  channelId: z.string().min(1),
  name: z.string().min(1),
  templateId: z.string().default("freeform"),
});

export const dashboardIdInput = z.object({ id: z.string().min(1) });

export const canvasBuildsInput = z.object({
  id: z.string().min(1),
  versionId: z.string().min(1).optional(),
});

export const canvasSourceInput = z.object({
  id: z.string().min(1),
  // Read a historical version's files instead of the head.
  versionId: z.string().optional(),
});

// Move the canvas's head back to an existing version (and rebuild it).
export const revertCanvasInput = z.object({
  id: z.string().min(1),
  versionId: z.string().min(1),
  expectedCurrentVersionId: z.string().nullable(),
});

// Promote a draft version to the canvas's live head (and build it if needed).
export const promoteCanvasInput = z.object({
  id: z.string().min(1),
  versionId: z.string().min(1),
  expectedCurrentVersionId: z.string().nullable(),
});

// Persist the author-written context (markdown) shown in the Context tab and
// passed to generation tasks.
export const saveContextInput = z.object({
  id: z.string().min(1),
  context: z.string(),
});

// Rename a canvas (its display title).
export const renameDashboardInput = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
});

export const fileDashboardInput = z.object({
  id: z.string().min(1),
  channelId: z.string().min(1),
});

// Set (or clear, when taskId is null) the canvas's generation-task association.
export const setGenerationTaskInput = z.object({
  id: z.string().min(1),
  taskId: z.string().nullable(),
});

// Pin (or unpin) a canvas to its channel (shared across users).
export const setPinnedInput = z.object({
  id: z.string().min(1),
  pinned: z.boolean(),
});

// File a rendering error against the build that threw it. Only the error's
// class name crosses the boundary — the full message can carry viewer data.
export const reportCanvasErrorInput = z.object({
  id: z.string().min(1),
  buildId: z.string().min(1),
  errorType: z.string().min(1).max(64),
});
export const canvasStateScopeSchema = z.enum(["user", "shared"]);
export type CanvasStateScope = z.infer<typeof canvasStateScopeSchema>;

// One key of a canvas's runtime key-value state (the ph.state store).
export const canvasStateEntrySchema = z.object({
  scope: canvasStateScopeSchema,
  key: z.string(),
  value: z.unknown(),
  updatedAt: z.string(),
});
export type CanvasStateEntry = z.infer<typeof canvasStateEntrySchema>;

export const canvasStateListInput = z.object({
  id: z.string().min(1),
  scope: canvasStateScopeSchema.optional(),
});

// State values cross to the backend as JSON, where a null value means "delete
// this key". JSON.stringify turns non-finite numbers (NaN, Infinity) into
// null, so without this guard a canvas storing one (e.g. total / count with a
// zero count) would silently delete the key and still get a success response.
// An explicit null stays the delete sentinel.
function isStorableStateValue(value: unknown): boolean {
  try {
    JSON.stringify(value, (_key, entry) => {
      if (typeof entry === "number" && !Number.isFinite(entry)) {
        throw new Error("non-finite number");
      }
      return entry;
    });
    return true;
  } catch {
    return false;
  }
}

// A null value deletes the key.
export const canvasStateSetInput = z.object({
  id: z.string().min(1),
  scope: canvasStateScopeSchema,
  key: z.string().min(1).max(200),
  value: z.unknown().refine(isStorableStateValue, {
    message: "value must not contain non-finite numbers (NaN or Infinity)",
  }),
});

// One registered action verb, as the host renders it before invoking.
export const canvasActionDefinitionSchema = z.object({
  verb: z.string(),
  summary: z.string(),
  destructive: z.boolean(),
});
export type CanvasActionDefinition = z.infer<
  typeof canvasActionDefinitionSchema
>;

export const canvasActionInvokeInput = z.object({
  id: z.string().min(1),
  verb: z.string().min(1).max(64),
  payload: z.record(z.string(), z.unknown()).default({}),
});

export const canvasActionResultSchema = z.object({
  verb: z.string(),
  result: z.record(z.string(), z.unknown()),
});
export type CanvasActionResult = z.infer<typeof canvasActionResultSchema>;

export const requestCanvasAgentInput = canvasAgentRequestInputSchema.extend({
  id: z.string().min(1),
});
