import {
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import { TITLE_GENERATOR_SERVICE } from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import { TASK_SERVICE } from "@posthog/core/task-detail/identifiers";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import {
  type Adapter,
  type CloudRegion,
  getCloudUrlFromRegion,
  type Task,
  type WorkspaceMode,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { isPlaceholderCanvasName } from "./canvasNaming";
import { buildCanvasGenerationPrompt } from "./generationPrompt";

export interface GenerateCanvasInput {
  /**
   * The canvas being generated or edited, when the surface already knows it.
   * Channel-composer runs omit it: the agent resolves the target itself
   * (building on a matching existing canvas, or creating a named one), so no
   * canvas-side effects run here.
   */
  dashboardId?: string;
  /** The target's title; set whenever dashboardId is. */
  name?: string;
  templateId?: string;
  instruction: string;
  /** True when the canvas already has published source (an edit, not a first build). */
  isEdit: boolean;
  /** First builds only: point the agent at the known-good starter scaffold. */
  useStarter?: boolean;
  /** Backend channel (task channel UUID) that owns the canvas and the task. */
  channelId: string;
  channelName: string;
  /** The channel's CONTEXT.md, passed as background for the run. */
  channelContext?: string;
  adapter?: Adapter;
  model?: string;
  reasoningLevel?: string;
  workspaceMode?: WorkspaceMode;
  /** Signed-in cloud region, used to resolve a model for cloud runs. */
  cloudRegion: CloudRegion | null | undefined;
}

/**
 * Host-side effects a generation needs that are transport-specific (the
 * desktop renderer reaches them over tRPC, web calls services directly).
 * The hook supplies an implementation; the service owns the orchestration.
 */
export interface CanvasGenerationGateway {
  /** File the task into the channel feed (best-effort). */
  fileTask(channelId: string, taskId: string): Promise<void>;
  /** Record the task as the canvas's in-flight generation run. */
  setGenerationTask(dashboardId: string, taskId: string): Promise<void>;
  /** Rename the canvas (auto-naming a placeholder title). */
  renameCanvas(dashboardId: string, name: string): Promise<void>;
  /** Invalidate task caches once the created task is ready. */
  onTaskReady?(task: Task): void;
  /** The canvas was auto-named after the run started (update trackers/toasts). */
  onAutoNamed?(taskId: string, title: string): void;
}

export type GenerateCanvasResult =
  | { ok: true; taskId: string }
  | { ok: false; reason: "no-model" }
  | { ok: false; reason: "create-failed"; error: string };

/**
 * Orchestrates canvas generation: resolves a model, builds the skills-routing
 * prompt, starts the (repo-less, unattended) task, files it to the channel,
 * records it on the canvas, and auto-names placeholder canvases. UI hooks are
 * thin adapters over this service — presentation (toasts, spinners, cache
 * invalidation) stays in the caller.
 */
@injectable()
export class CanvasApplicationService {
  constructor(
    @inject(TASK_SERVICE)
    private readonly taskService: TaskService,
    @inject(REPORT_MODEL_RESOLVER)
    private readonly modelResolver: ReportModelResolver,
    @inject(TITLE_GENERATOR_SERVICE)
    private readonly titleGenerator: TitleGeneratorService,
  ) {}

  async generateCanvas(
    input: GenerateCanvasInput,
    gateway: CanvasGenerationGateway,
  ): Promise<GenerateCanvasResult> {
    const {
      adapter = "claude",
      // Defaults to a cloud run — canvas generation should never tie up (or
      // depend on) the local machine. The dev-only picker can override to
      // "local" to test a local build of these features before merging.
      workspaceMode = "cloud",
    } = input;

    // A cloud run requires an explicit adapter + model (the API rejects a
    // cloud runtime without a model). Resolve the caller's pick — or the
    // adapter's server default when none — validated against the gateway so a
    // stale id can't 403 the run.
    let model: string | undefined = input.model;
    if (workspaceMode === "cloud") {
      model = input.cloudRegion
        ? await this.modelResolver.resolveDefaultModel(
            getCloudUrlFromRegion(input.cloudRegion),
            adapter,
            input.model,
          )
        : undefined;
      if (!model) {
        return { ok: false, reason: "no-model" };
      }
    }

    const result = await this.taskService.createTask(
      {
        content: buildCanvasGenerationPrompt({
          dashboardId: input.dashboardId,
          name: input.name,
          channelName: input.channelName,
          channelId: input.channelId,
          templateId: input.templateId,
          instruction: input.instruction,
          isEdit: input.isEdit,
          useStarter: input.useStarter,
        }),
        taskDescription: input.name
          ? `Generate canvas "${input.name}"`
          : `Generate a canvas in #${input.channelName}`,
        // Unattended generation: run in auto mode so it doesn't stall on
        // edit-approval prompts.
        executionMode: "auto" as const,
        workspaceMode,
        adapter,
        model,
        reasoningLevel: input.reasoningLevel,
        allowNoRepo: true,
        channelContext: input.channelContext,
        channelName: input.channelName,
        channelId: input.channelId,
      },
      (output) => gateway.onTaskReady?.(output.task),
    );

    if (!result.success) {
      return { ok: false, reason: "create-failed", error: result.error };
    }

    const task = result.data.task;
    // File into the channel — best-effort (a failure shouldn't undo a started
    // task).
    void gateway.fileTask(input.channelId, task.id).catch(() => {});

    // Canvas-side effects only apply when the surface pre-resolved a target;
    // target-less runs leave them to the agent, which resolves or creates the
    // canvas itself.
    const dashboardId = input.dashboardId;
    if (dashboardId) {
      // The generation-task write is awaited so a caller that navigates to the
      // canvas right after generate() lands on the generating view, not the
      // empty hero.
      await gateway.setGenerationTask(dashboardId, task.id).catch(() => {});

      // Auto-name a still-unnamed canvas from its generation prompt, using the
      // same helper model that names tasks. Best-effort: a failure (or a user
      // who already named the canvas) leaves the existing title untouched.
      if (input.name && isPlaceholderCanvasName(input.name)) {
        void this.titleGenerator
          .generateCanvasName(input.instruction)
          .then(async (generated) => {
            const title = generated?.trim();
            if (title) {
              await gateway.renameCanvas(dashboardId, title);
              gateway.onAutoNamed?.(task.id, title);
            }
          })
          .catch(() => {});
      }
    }

    return { ok: true, taskId: task.id };
  }
}
