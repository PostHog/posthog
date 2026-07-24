import {
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { getCloudUrlFromRegion, type WorkspaceMode } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  buildContextGenerationPrompt,
  contextMdTaskTitle,
} from "@posthog/ui/features/canvas/contextPrompt";
import { channelFeedQueryKey } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { channelFeedMessagesQueryKey } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { resolveBackendChannelId } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { usePreviewConfig } from "@posthog/ui/features/task-detail/hooks/usePreviewConfig";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

interface GenerateContextInput {
  /** The desktop folder/context id — also the /website route param. */
  channelId: string;
  channelName: string;
  /** What the user says this context is about; seeds the plan. */
  description: string;
  workspaceMode?: WorkspaceMode;
}

// Launches the plan-mode session that builds a context's CONTEXT.md. The task
// runs repo-less (the agent attaches a repo lazily and asks to clarify if it
// can't find the right one) and starts in plan mode, seeded by the user's
// description, so the user shapes the document before it publishes via the
// PostHog MCP. Defaults to a cloud run so generation never ties up (or depends
// on) the local machine. Returns the created task, or null on failure.
//
// Channel-agnostic on purpose: the create-context dialog calls this with a
// freshly-created context's id (no bound hook possible before it exists), and
// the CONTEXT.md empty state calls it with the existing context.
export function useGenerateContext() {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const modelResolver = useService<ReportModelResolver>(REPORT_MODEL_RESOLVER);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const { invalidateTasks } = useCreateTask();
  const { fileTask } = useChannelTaskMutations();
  const client = useOptionalAuthenticatedClient();
  const [isStarting, setIsStarting] = useState(false);

  // Resolve adapter + model the same way the composer does. A cloud run rejects
  // a task with no model ("required when selecting a cloud runtime"), so this
  // headless launch must supply one rather than relying on a composer's picker.
  const adapter = useSettingsStore((s) => s.lastUsedAdapter);
  const { modelOption } = usePreviewConfig(adapter);
  const currentModel =
    modelOption?.type === "select" ? modelOption.currentValue : undefined;

  const generate = useCallback(
    async ({
      channelId,
      channelName,
      description,
      workspaceMode = "cloud",
    }: GenerateContextInput): Promise<Task | null> => {
      setIsStarting(true);
      try {
        // The composer's picker may not have resolved yet (or the user never
        // used it), so fall back to the adapter's server default the way the
        // inbox one-click flows do; the resolver validates against the gateway.
        // Without a model a cloud run is rejected server-side after the context
        // was already created — hard-stop with a clear toast instead.
        let model = currentModel;
        if (workspaceMode === "cloud") {
          model = cloudRegion
            ? await modelResolver.resolveDefaultModel(
                getCloudUrlFromRegion(cloudRegion),
                adapter ?? "claude",
                currentModel,
              )
            : undefined;
          if (!model) {
            toastError(
              "Couldn't start the planning session",
              "No model is configured for cloud runs.",
            );
            return null;
          }
        }
        // Own the task on the backend channel so it lands in the context feed
        // (not just Recents). Best-effort: fall back to no channel on failure.
        const backendChannelId = await resolveBackendChannelId(
          client,
          channelName,
        ).catch(() => undefined);

        const result = await taskService.createTask(
          {
            content: buildContextGenerationPrompt({
              channelName,
              channelId,
              description,
            }),
            taskDescription: contextMdTaskTitle(channelName),
            workspaceMode,
            adapter: adapter ?? "claude",
            channelId: backendChannelId,
            // Plan mode: the agent proposes the document and waits for approval
            // before publishing, so the user co-designs CONTEXT.md.
            executionMode: "plan",
            allowNoRepo: true,
            // A cloud run pairs a runtime adapter with a model, and the API
            // rejects one without the other. Since this flow never surfaces a
            // model picker, pass the gateway-validated model resolved above.
            model,
          },
          (output) => invalidateTasks(output.task),
        );

        if (!result.success) {
          toastError("Couldn't start the planning session", result.error);
          return null;
        }

        const task = result.data.task;
        // File into the context so its Recents/Artifacts tabs pick it up.
        // Best-effort — a failure here shouldn't undo a started task.
        void fileTask(channelId, task.id, task.title).catch(() => {});
        if (backendChannelId) {
          // Announce the CONTEXT.md build in the channel feed (durable, team-
          // visible), keyed on the backend channel — the same id the task cards
          // use. Timestamped just before the task so it sorts above the card.
          // Best-effort.
          const buildingAt = new Date(
            new Date(task.created_at).getTime() - 1,
          ).toISOString();
          void client
            ?.postChannelFeedMessage(backendChannelId, {
              event: "context_md_building",
              payload: { context_name: channelName },
              createdAt: buildingAt,
            })
            .then(() =>
              queryClient.invalidateQueries({
                queryKey: channelFeedMessagesQueryKey(backendChannelId),
              }),
            )
            .catch(() => {});
          // Show the new card in the context feed without waiting for the poll.
          void queryClient.invalidateQueries({
            queryKey: channelFeedQueryKey(backendChannelId),
          });
        }
        // Refresh the workspace cache so the new cloud workspace row appears and
        // the task view resolves the cloud run instead of the repo-picker prompt.
        void queryClient.invalidateQueries({
          queryKey: trpc.workspace.getAll.queryKey(),
        });
        return task;
      } finally {
        setIsStarting(false);
      }
    },
    [
      taskService,
      trpc,
      queryClient,
      invalidateTasks,
      fileTask,
      client,
      adapter,
      currentModel,
      modelResolver,
      cloudRegion,
    ],
  );

  return { generate, isStarting };
}
