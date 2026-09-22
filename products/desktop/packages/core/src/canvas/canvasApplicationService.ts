import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import {
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import { TITLE_GENERATOR_SERVICE } from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import { TASK_SERVICE } from "@posthog/core/task-detail/identifiers";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  type Adapter,
  type CloudRegion,
  getCloudUrlFromRegion,
  type Task,
  type WorkspaceMode,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { isPlaceholderCanvasName } from "./canvasNaming";
import {
  buildCanvasGenerationPrompt,
  buildGridCanvasGenerationPrompt,
  buildPlacementGenerationPrompt,
} from "./generationPrompt";

export interface GenerateCanvasInput {
  dashboardId: string;
  name: string;
  templateId?: string;
  instruction: string;
  /** When set, the run fills ONE placement on a grid canvas instead of
   * authoring the canvas itself (composing-grid-canvases skill routing). */
  placement?: { placementId: string; w: number; h: number };
  /** "grid" routes a whole-canvas run (no placement) to the grid skill:
   * the agent edits the layout and its components instead of authoring a
   * freeform canvas app. */
  canvasKind?: "grid";
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

// Unattended canvas runs default to Claude Sonnet 5 at high reasoning effort.
// The resolver validates the id against the gateway's model list, so when it's
// absent the run falls back to the server default instead of failing — and the
// effort default follows the model: it only applies when the preferred model
// actually resolved, because other models may not support that effort tier.
const CANVAS_PREFERRED_ADAPTER = "claude" as const;
const CANVAS_PREFERRED_MODEL = "claude-sonnet-5";
const CANVAS_PREFERRED_REASONING = "high";

const TASK_TITLE_MAX = 80;

function truncateForTitle(text: string): string {
  const flattened = text.replace(/\s+/g, " ").trim();
  return flattened.length > TASK_TITLE_MAX
    ? `${flattened.slice(0, TASK_TITLE_MAX - 1)}…`
    : flattened;
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
  private readonly log: ScopedLogger;

  constructor(
    @inject(TASK_SERVICE)
    private readonly taskService: TaskService,
    @inject(REPORT_MODEL_RESOLVER)
    private readonly modelResolver: ReportModelResolver,
    @inject(TITLE_GENERATOR_SERVICE)
    private readonly titleGenerator: TitleGeneratorService,
    @inject(ROOT_LOGGER) rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("canvas-application");
  }

  async generateCanvas(
    input: GenerateCanvasInput,
    gateway: CanvasGenerationGateway,
  ): Promise<GenerateCanvasResult> {
    try {
      return await this.generateCanvasInternal(input, gateway);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log.error("Canvas generation failed", { error: message });
      return { ok: false, reason: "create-failed", error: message };
    }
  }

  private async generateCanvasInternal(
    input: GenerateCanvasInput,
    gateway: CanvasGenerationGateway,
  ): Promise<GenerateCanvasResult> {
    const {
      adapter = CANVAS_PREFERRED_ADAPTER,
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
            input.model ??
              // The preferred id only fits its own adapter; a caller-picked
              // other adapter resolves to that adapter's server default.
              (adapter === CANVAS_PREFERRED_ADAPTER
                ? CANVAS_PREFERRED_MODEL
                : null),
          )
        : undefined;
      if (!model) {
        return { ok: false, reason: "no-model" };
      }
    }

    const result = await this.taskService.createTask(
      {
        content: input.placement
          ? buildPlacementGenerationPrompt({
              dashboardId: input.dashboardId,
              name: input.name,
              channelName: input.channelName,
              instruction: input.instruction,
              placementId: input.placement.placementId,
              boxWidth: input.placement.w,
              boxHeight: input.placement.h,
            })
          : input.canvasKind === "grid"
            ? buildGridCanvasGenerationPrompt({
                dashboardId: input.dashboardId,
                name: input.name,
                channelName: input.channelName,
                instruction: input.instruction,
              })
            : buildCanvasGenerationPrompt({
                dashboardId: input.dashboardId,
                name: input.name,
                channelName: input.channelName,
                templateId: input.templateId,
                instruction: input.instruction,
              }),
        // A placement fill is named after its widget — every fill on the same
        // canvas would otherwise share one useless "Generate canvas Home" title.
        taskDescription: input.placement
          ? `Generate widget: ${truncateForTitle(input.instruction)}`
          : input.canvasKind === "grid"
            ? `Update canvas "${input.name}": ${truncateForTitle(input.instruction)}`
            : input.name
              ? `Generate canvas "${input.name}"`
              : `Generate a canvas in ${channelDisplayReference(input.channelName)}`,
        // Unattended generation: auto mode relays every MCP approval to the
        // desktop and blocks the run until someone answers. What still applies
        // in bypass mode: do_not_use tools stay denied, tools on MCP servers
        // relayed to the user's machine still need their approval, and PostHog
        // exec sub-tools matching the run's permission regex are still relayed
        // for one. It does NOT contain the run to the canvas API.
        //
        // TODO(canvas mcp scopes): bypassing is only defensible once this run's
        // token is narrowed. A client-created run sends runSource "manual",
        // which resolves to "full" PostHog MCP scopes in
        // products/tasks/backend/facade/api.py (insight, dashboard and flag
        // writes, plus SQL), while the prompt carries channel context and canvas
        // comments other people wrote. ReviewHog's sandbox passes an explicit
        // scope list for exactly this reason (see REVIEW_MCP_SCOPES), but the
        // REST run-create surface exposes no scope field, so a client cannot ask
        // for one. Both canvas surfaces CAN answer an approval today
        // (CanvasPermissionDialog on freeform, Review request on a grid tile),
        // so this mode also switches off a gate that works.
        executionMode: "bypassPermissions" as const,
        workspaceMode,
        adapter,
        model,
        reasoningLevel:
          input.reasoningLevel ??
          (model === CANVAS_PREFERRED_MODEL
            ? CANVAS_PREFERRED_REASONING
            : undefined),
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
    void gateway.fileTask(input.channelId, task.id).catch((error) => {
      this.log.warn("Failed to file canvas generation task", { error });
    });

    const dashboardId = input.dashboardId;
    // A placement fill is scoped to one tile: the placement row carries the
    // task id, so the whole canvas must not read as "generating" (nor get
    // auto-renamed from a single widget's prompt).
    if (input.placement) {
      return { ok: true, taskId: task.id };
    }
    await gateway.setGenerationTask(dashboardId, task.id).catch((error) => {
      this.log.warn("Failed to record canvas generation task", { error });
    });

    if (isPlaceholderCanvasName(input.name)) {
      void this.titleGenerator
        .generateCanvasName(input.instruction)
        .then(async (generated) => {
          const title = generated?.trim();
          if (title) {
            await gateway.renameCanvas(dashboardId, title);
            gateway.onAutoNamed?.(task.id, title);
          }
        })
        .catch((error) => {
          this.log.warn("Failed to auto-name canvas", { error });
        });
    }

    return { ok: true, taskId: task.id };
  }
}
