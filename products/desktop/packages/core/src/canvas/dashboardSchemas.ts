import { CANVAS_PLATFORM_MANIFEST } from "@posthog/shared";
import { z } from "zod";

// A canvas record from the PostHog canvases API, normalized to camelCase and
// epoch-ms timestamps. Source code and version history are NOT part of the
// record — they live behind the source/versions endpoints, and the rendered
// output behind the build lifecycle.
export const dashboardRecordSchema = z.object({
  id: z.string(),
  // The backend channel (task channel UUID) this canvas belongs to.
  channelId: z.string(),
  name: z.string(),
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
  // Whether this is the channel's home board (at most one per channel).
  isHome: z.boolean().default(false),
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

export const createDashboardInput = z.object({
  channelId: z.string().min(1),
  name: z.string().min(1),
  templateId: z.string().default("freeform"),
});

export const dashboardIdInput = z.object({ id: z.string().min(1) });

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

// Persist the author-written context (markdown) shown in the Context tab and
// passed to generation tasks.
export const saveContextInput = z.object({
  id: z.string().min(1),
  context: z.string(),
});

export const ensureHomeCanvasInput = z.object({
  channelId: z.string().min(1),
});

// Rename a canvas (its display title).
export const renameDashboardInput = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
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
