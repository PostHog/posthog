import {
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import { TITLE_GENERATOR_SERVICE } from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  type Adapter,
  getCloudUrlFromRegion,
  type WorkspaceMode,
} from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { buildFreeformGenerationPrompt } from "@posthog/ui/features/canvas/freeformPrompt";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import {
  isPlaceholderCanvasName,
  useDashboardMutations,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import { useCanvasGenerationTrackerStore } from "@posthog/ui/features/canvas/stores/canvasGenerationTrackerStore";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

// Kicks off freeform canvas generation as a repo-less task, files it to the
// channel, and records it as the canvas's generation task (in the canvas's meta)
// so every client's canvas view tracks the in-flight run. Canvas generation
// reads PostHog data via the MCP rather than repo code, so no repo is selected
// up front — the agent attaches one lazily only if it decides it needs one. The
// task runs as a cloud run (not a local agent) so generation proceeds
// server-side regardless of which client kicked it off, and the agent publishes
// the result via the `desktop-file-system-canvas-partial-update` MCP tool.
export function useGenerateFreeformCanvas(args: {
  channelId: string;
  channelName: string;
  /**
   * The channel's CONTEXT.md, when the surface already fetched it (the channel
   * composer receives it as a prop). Passing the property — even with an
   * undefined value — marks the caller as its owner and skips this hook's own
   * fetch; omit it entirely to let the hook fetch.
   */
  channelContext?: string;
}) {
  const { channelId, channelName } = args;
  const taskService = useService<TaskService>(TASK_SERVICE);
  const modelResolver = useService<ReportModelResolver>(REPORT_MODEL_RESOLVER);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const titleGenerator = useService<TitleGeneratorService>(
    TITLE_GENERATOR_SERVICE,
  );
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const { invalidateTasks } = useCreateTask();
  const { fileTask } = useChannelTaskMutations();
  const { setGenerationTask, renameDashboard } = useDashboardMutations();
  // The channel's CONTEXT.md, passed to the agent as optional background so the
  // generated canvas starts with the shared context. Absent/empty is fine.
  const callerOwnsContext = "channelContext" in args;
  const { data: instructions } = useFolderInstructions(channelId, {
    enabled: !callerOwnsContext,
  });
  const channelContext = callerOwnsContext
    ? args.channelContext
    : instructions?.content;
  const [isStarting, setIsStarting] = useState(false);

  const generate = useCallback(
    async (opts: {
      // The canvas being generated — per call, so surfaces that create the
      // canvas at submit time (the channel composer) can use one hook instance.
      dashboardId: string;
      name: string;
      templateId?: string;
      instruction: string;
      currentCode?: string;
      // Backend channel UUID that owns the created task, so it lands in the
      // channel's task feed like a plain composer submit.
      backendChannelId?: string;
      // The composer's picks, when the surface exposes model/effort selectors.
      // The model is validated against the gateway (falling back to the
      // adapter's default) so a stale id can't 403 the run.
      adapter?: Adapter;
      model?: string;
      reasoningLevel?: string;
      // Default on (opt out in the bar): seed the starter scaffold on first build.
      useStarter?: boolean;
      // Dev-only override (the bar exposes a local/cloud picker in dev so a
      // local build of these features can be tested before merging). Production
      // always runs in the cloud — see the default below.
      workspaceMode?: WorkspaceMode;
    }): Promise<string | null> => {
      const {
        dashboardId,
        name,
        templateId,
        instruction,
        currentCode,
        backendChannelId,
        adapter = "claude",
        reasoningLevel,
        useStarter,
        // Defaults to a cloud run — canvas generation should never tie up (or
        // depend on) the local machine, and it's never the sticky last-used
        // workspace mode. The dev-only picker can override to "local" to test a
        // local build of these features before merging.
        workspaceMode = "cloud",
      } = opts;
      setIsStarting(true);
      try {
        // A cloud run requires an explicit adapter + model (the API rejects a
        // cloud runtime without a model). Resolve the caller's pick — or the
        // adapter's server default when none — the same way the inbox one-click
        // flows do; the resolver validates against the gateway, so a stale id
        // can't slip through and 403 the run.
        let model: string | undefined = opts.model;
        if (workspaceMode === "cloud") {
          model = cloudRegion
            ? await modelResolver.resolveDefaultModel(
                getCloudUrlFromRegion(cloudRegion),
                adapter,
                opts.model,
              )
            : undefined;
          if (!model) {
            toast.error("Couldn't start canvas generation", {
              description: "No model is configured for cloud runs.",
            });
            return null;
          }
        }

        const result = await taskService.createTask(
          {
            content: buildFreeformGenerationPrompt({
              dashboardId,
              name,
              channelName,
              templateId,
              instruction,
              currentCode,
              useStarter,
            }),
            taskDescription: `Generate canvas "${name}"`,
            // Unattended generation: run in auto mode so it doesn't stall on edit-approval prompts.
            executionMode: "auto" as const,
            workspaceMode,
            adapter,
            model,
            reasoningLevel,
            allowNoRepo: true,
            channelContext,
            channelName,
            channelId: backendChannelId,
          },
          (output) => invalidateTasks(output.task),
        );

        if (!result.success) {
          toastError("Couldn't start canvas generation", result.error);
          return null;
        }

        const task = result.data.task;
        // File into the channel + record as the canvas's generation task. Both
        // are best-effort: a failure here shouldn't undo a started task. The
        // generation-task write is awaited so a caller that navigates to the
        // canvas right after generate() lands on the generating view (with the
        // run in the side panel), not the empty hero.
        void fileTask(channelId, task.id, task.title).catch(() => {});
        await setGenerationTask(dashboardId, task.id).catch(() => {});
        // Track this run so a toast (with a link back here) fires when it
        // finishes, even after the user navigates to another canvas.
        useCanvasGenerationTrackerStore
          .getState()
          .track({ taskId: task.id, dashboardId, channelId, name });
        // Refresh the workspace cache so the new cloud workspace row appears and
        // the task view resolves the cloud run instead of the repo-picker prompt.
        void queryClient.invalidateQueries({
          queryKey: trpc.workspace.getAll.queryKey(),
        });
        // Auto-name a still-unnamed canvas from its generation prompt, using the
        // same helper model that names tasks. Best-effort: a failure (or a user
        // who already named the canvas) leaves the existing title untouched.
        if (isPlaceholderCanvasName(name)) {
          void titleGenerator
            .generateCanvasName(instruction)
            .then(async (generated) => {
              const title = generated?.trim();
              if (title) {
                await renameDashboard(dashboardId, title);
                // Keep the tracked generation's name in sync so its completion
                // toast reads the real title, not "Untitled canvas".
                useCanvasGenerationTrackerStore
                  .getState()
                  .updateName(task.id, title);
              }
            })
            .catch(() => {});
        }
        return task.id;
      } finally {
        setIsStarting(false);
      }
    },
    [
      taskService,
      modelResolver,
      cloudRegion,
      titleGenerator,
      trpc,
      queryClient,
      invalidateTasks,
      fileTask,
      setGenerationTask,
      renameDashboard,
      channelId,
      channelName,
      channelContext,
    ],
  );

  return { generate, isStarting };
}
