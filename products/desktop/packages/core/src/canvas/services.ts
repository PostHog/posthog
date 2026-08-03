import type {
  CanvasBuildActionInput,
  CanvasBuildLifecycle,
  CanvasBuildRecord,
} from "./canvasBuildSchemas";
import type { ChannelTaskRecord } from "./channelTaskSchemas";
import type {
  CanvasSource,
  CanvasVersion,
  DashboardRecord,
} from "./dashboardSchemas";
import type {
  CanvasCaptureConfig,
  CanvasCaptureInput,
  CanvasCaptureResult,
  CanvasDataQueryInput,
  CanvasDataResult,
  CanvasLoadInsightInput,
} from "./freeformSchemas";
import type { CanvasTemplate, CanvasTemplateSummary } from "./templateSchemas";

// Structural service interfaces the host-router routers depend on. The concrete
// implementations live in the desktop app's main process and are bound to the
// tokens in identifiers.ts; the router only needs the method surface.

export interface ICanvasTemplatesService {
  list(): CanvasTemplateSummary[];
  get(id: string): CanvasTemplate | undefined;
  /**
   * The freeform (React iframe) system prompt for a template, falling back to
   * the generic freeform sandbox prompt.
   */
  freeformSystemPromptFor(id: string | undefined): string;
}

export interface IDashboardsService {
  list(channelId: string): Promise<DashboardRecord[]>;
  get(id: string): Promise<DashboardRecord | null>;
  create(input: {
    channelId: string;
    name: string;
    templateId?: string;
  }): Promise<DashboardRecord>;
  saveContext(input: { id: string; context: string }): Promise<DashboardRecord>;
  setGenerationTask(input: {
    id: string;
    taskId: string | null;
  }): Promise<DashboardRecord>;
  setPinned(input: { id: string; pinned: boolean }): Promise<DashboardRecord>;
  // Read the canvas's source project (the head, or a historical version).
  getSource(input: { id: string; versionId?: string }): Promise<CanvasSource>;
  // The canvas's source-version history, newest first (metadata only).
  listVersions(id: string): Promise<CanvasVersion[]>;
  // Move the canvas's head back to an existing version and rebuild it.
  revertToVersion(input: {
    id: string;
    versionId: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasBuildRecord>;
  // Read a canvas's build lifecycle (pointers + recent builds).
  getBuilds(id: string): Promise<CanvasBuildLifecycle>;
  actOnBuild(input: CanvasBuildActionInput): Promise<CanvasBuildRecord>;
  rename(input: { id: string; name: string }): Promise<DashboardRecord>;
  // Idempotently create + seed a channel's home canvas, returning it.
  ensureHomeCanvas(channelId: string): Promise<DashboardRecord>;
  // Publish a fresh template version to the home canvas (non-destructive; the
  // prior version stays in history so the edit can be restored via revert).
  resetHomeCanvas(channelId: string): Promise<DashboardRecord>;
  delete(id: string): Promise<void>;
}

export interface ICanvasDataService {
  query(input: CanvasDataQueryInput): Promise<CanvasDataResult>;
  loadInsight(input: CanvasLoadInsightInput): Promise<CanvasDataResult>;
  capture(input: CanvasCaptureInput): Promise<CanvasCaptureResult>;
  captureConfig(): Promise<CanvasCaptureConfig>;
}

export interface IChannelTasksService {
  list(channelId: string): Promise<ChannelTaskRecord[]>;
  file(input: {
    channelId: string;
    taskId: string;
  }): Promise<ChannelTaskRecord>;
  // Unfile a task from its channel (clears the task's channel field).
  unfile(taskId: string): Promise<void>;
}
