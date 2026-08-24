import type {
  CanvasBuildActionInput,
  CanvasBuildLifecycle,
  CanvasBuildRecord,
} from "./canvasBuildSchemas";
import type { ChannelTaskRecord } from "./channelTaskSchemas";
import type {
  CanvasActionDefinition,
  CanvasActionResult,
  CanvasDraft,
  CanvasSource,
  CanvasStateEntry,
  CanvasStateScope,
  CanvasVersion,
  DashboardRecord,
} from "./dashboardSchemas";
import type {
  CanvasAgentRequestResult,
  CanvasCaptureConfig,
  CanvasCaptureInput,
  CanvasCaptureResult,
  CanvasDataQueryInput,
  CanvasDataResult,
  CanvasLoadInsightInput,
} from "./freeformSchemas";
import type {
  CanvasLayout,
  CanvasLayoutResult,
  LayoutOperation,
} from "./gridLayoutSchemas";
import type { CanvasTemplateSummary } from "./templateSchemas";

// Structural service interfaces the host-router routers depend on. The concrete
// implementations live in the desktop app's main process and are bound to the
// tokens in identifiers.ts; the router only needs the method surface.

export interface ICanvasTemplatesService {
  list(): CanvasTemplateSummary[];
}

export interface IDashboardsService {
  list(channelId: string): Promise<DashboardRecord[]>;
  // The component store: component-kind canvases visible to the caller.
  listComponents(input: { search?: string }): Promise<DashboardRecord[]>;
  get(id: string): Promise<DashboardRecord | null>;
  create(input: {
    channelId: string;
    name: string;
    templateId?: string;
  }): Promise<DashboardRecord>;
  // Get-or-create the caller's home grid canvas. Idempotent.
  home(): Promise<DashboardRecord>;
  // Read a grid canvas's layout (the head, or a historical version).
  getLayout(input: {
    id: string;
    versionId?: string;
  }): Promise<CanvasLayoutResult>;
  // Publish a complete layout as the new head (live immediately, no build).
  publishLayout(input: {
    id: string;
    layout: CanvasLayout;
    prompt?: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasLayoutResult>;
  // Apply surgical, guarded operations to the current layout.
  patchLayout(input: {
    id: string;
    operations: LayoutOperation[];
    prompt?: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasLayoutResult>;
  saveContext(input: { id: string; context: string }): Promise<DashboardRecord>;
  setGenerationTask(input: {
    id: string;
    taskId: string | null;
  }): Promise<DashboardRecord>;
  setPinned(input: { id: string; pinned: boolean }): Promise<DashboardRecord>;
  file(input: { id: string; channelId: string }): Promise<DashboardRecord>;
  // File a rendering error against the build that threw it (best-effort).
  reportError(input: {
    id: string;
    buildId: string;
    errorType: string;
  }): Promise<void>;
  // The canvas's readable ph.state entries (shared + the caller's own user rows).
  listState(input: {
    id: string;
    scope?: CanvasStateScope;
  }): Promise<CanvasStateEntry[]>;
  // Write one ph.state key; a null value deletes it.
  setState(input: {
    id: string;
    scope: CanvasStateScope;
    key: string;
    value: unknown;
  }): Promise<void>;
  // The action registry: every verb a canvas may declare and invoke.
  listActions(): Promise<CanvasActionDefinition[]>;
  // Invoke one registered action verb as the viewer.
  invokeAction(input: {
    id: string;
    verb: string;
    payload: Record<string, unknown>;
  }): Promise<CanvasActionResult>;
  // Read the canvas's source project (the head, or a historical version).
  getSource(input: { id: string; versionId?: string }): Promise<CanvasSource>;
  // The canvas's source-version history, newest first (metadata only).
  listVersions(id: string): Promise<CanvasVersion[]>;
  // The canvas's staged drafts, newest first, each with its latest build status.
  listDrafts(id: string): Promise<CanvasDraft[]>;
  // Make a draft version the canvas's live head (and build it if needed).
  promoteDraft(input: {
    id: string;
    versionId: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasBuildRecord>;
  // Move the canvas's head back to an existing version and rebuild it.
  revertToVersion(input: {
    id: string;
    versionId: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasBuildRecord>;
  // Read a canvas's build lifecycle, optionally including a historical build.
  getBuilds(input: {
    id: string;
    versionId?: string;
  }): Promise<CanvasBuildLifecycle>;
  actOnBuild(input: CanvasBuildActionInput): Promise<CanvasBuildRecord>;
  rename(input: { id: string; name: string }): Promise<DashboardRecord>;
  delete(id: string): Promise<void>;
  requestAgent(input: {
    id: string;
    prompt: string;
  }): Promise<CanvasAgentRequestResult>;
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
