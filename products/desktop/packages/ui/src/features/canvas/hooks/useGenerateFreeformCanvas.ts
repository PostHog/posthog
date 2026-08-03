import type {
  CanvasApplicationService,
  CanvasGenerationGateway,
} from "@posthog/core/canvas/canvasApplicationService";
import { CANVAS_APPLICATION_SERVICE } from "@posthog/core/canvas/identifiers";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import type { Adapter, WorkspaceMode } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useDashboardMutations } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import { useCanvasGenerationTrackerStore } from "@posthog/ui/features/canvas/stores/canvasGenerationTrackerStore";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

// Thin mutation adapter over CanvasApplicationService (@posthog/core), which
// owns the generation orchestration: model resolution, the skills-routing
// prompt, task creation, channel filing, generation-task recording, and
// auto-naming. This hook contributes only presentation state — the isStarting
// flag, error toasts, the completion-toast tracker, and query-cache
// invalidation — plus the tRPC-backed gateway the renderer uses for canvas
// persistence effects.
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
  const canvasApplication = useService<CanvasApplicationService>(
    CANVAS_APPLICATION_SERVICE,
  );
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
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
      /** True when the canvas already has published source (a follow-up edit
       * rather than a first build). The agent re-reads the live source itself
       * through the canvas tools. */
      isEdit?: boolean;
      // The composer's picks, when the surface exposes model/effort selectors.
      adapter?: Adapter;
      model?: string;
      reasoningLevel?: string;
      // Default on (opt out in the bar): seed the starter scaffold on first build.
      useStarter?: boolean;
      // Dev-only override (the bar exposes a local/cloud picker in dev so a
      // local build of these features can be tested before merging). Production
      // always runs in the cloud.
      workspaceMode?: WorkspaceMode;
    }): Promise<string | null> => {
      const { dashboardId, name, instruction } = opts;
      setIsStarting(true);
      try {
        const gateway: CanvasGenerationGateway = {
          fileTask: async (cid, taskId) => {
            await fileTask(cid, taskId);
          },
          setGenerationTask: async (id, taskId) => {
            await setGenerationTask(id, taskId);
          },
          renameCanvas: async (id, title) => {
            await renameDashboard(id, title);
          },
          onTaskReady: (task) => invalidateTasks(task),
          // Keep the tracked generation's name in sync so its completion toast
          // reads the real title, not "Untitled canvas".
          onAutoNamed: (taskId, title) =>
            useCanvasGenerationTrackerStore
              .getState()
              .updateName(taskId, title),
        };

        const result = await canvasApplication.generateCanvas(
          {
            dashboardId,
            name,
            templateId: opts.templateId,
            instruction,
            isEdit: opts.isEdit ?? false,
            useStarter: opts.useStarter,
            channelId,
            channelName,
            channelContext,
            adapter: opts.adapter,
            model: opts.model,
            reasoningLevel: opts.reasoningLevel,
            workspaceMode: opts.workspaceMode,
            cloudRegion,
          },
          gateway,
        );

        if (!result.ok) {
          if (result.reason === "no-model") {
            toast.error("Couldn't start canvas generation", {
              description: "No model is configured for cloud runs.",
            });
          } else {
            toastError("Couldn't start canvas generation", result.error);
          }
          return null;
        }

        // Track this run so a toast (with a link back here) fires when it
        // finishes, even after the user navigates to another canvas.
        useCanvasGenerationTrackerStore
          .getState()
          .track({ taskId: result.taskId, dashboardId, channelId, name });
        // Refresh the workspace cache so the new cloud workspace row appears and
        // the task view resolves the cloud run instead of the repo-picker prompt.
        void queryClient.invalidateQueries({
          queryKey: trpc.workspace.getAll.queryKey(),
        });
        return result.taskId;
      } finally {
        setIsStarting(false);
      }
    },
    [
      canvasApplication,
      cloudRegion,
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
