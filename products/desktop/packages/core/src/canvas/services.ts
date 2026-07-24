import type { ChannelTaskRecord } from "./channelTaskSchemas";
import type { DashboardRecord, DashboardSummary } from "./dashboardSchemas";
import type {
  CanvasCaptureConfig,
  CanvasCaptureInput,
  CanvasCaptureResult,
  CanvasDataQueryInput,
  CanvasDataResult,
  CanvasLoadInsightInput,
  FreeformVersion,
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
  list(channelId: string): Promise<DashboardSummary[]>;
  get(id: string): Promise<DashboardRecord | null>;
  create(input: {
    channelId: string;
    name: string;
    templateId?: string;
  }): Promise<DashboardRecord>;
  saveFreeform(input: {
    id: string;
    name?: string;
    code: string;
    versions: FreeformVersion[];
    currentVersionId?: string;
  }): Promise<DashboardRecord>;
  setGenerationTask(input: {
    id: string;
    taskId: string | null;
  }): Promise<DashboardRecord>;
  setPinned(input: { id: string; pinned: boolean }): Promise<DashboardRecord>;
  rename(input: { id: string; name: string }): Promise<DashboardRecord>;
  // Idempotently create + seed a channel's home canvas, returning it.
  ensureHomeCanvas(channelId: string): Promise<DashboardRecord>;
  // Append a fresh template version to the home canvas (non-destructive; the
  // prior version stays in history so the edit can be restored via undo).
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
    taskTitle: string;
  }): Promise<ChannelTaskRecord>;
  unfile(id: string): Promise<void>;
}
