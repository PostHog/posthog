import { PI_SESSION_CONTROLLER } from "@posthog/core/pi-runtime/identifiers";
import type { PiSessionController } from "@posthog/core/pi-runtime/piSessionController";
import {
  deriveTaskRunState,
  narrowFullTask,
} from "@posthog/core/sidebar/buildSidebarData";
import { isTaskActivelyRunning } from "@posthog/core/sidebar/taskRunning";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { ArchiveRunningTaskDialog } from "@posthog/ui/features/sidebar/components/ArchiveRunningTaskDialog";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { type ReactElement, useCallback, useState } from "react";
import { useStore } from "zustand";
import { shallow } from "zustand/shallow";

const log = logger.scope("archive-task");

export interface TaskArchive {
  /** Archives the task, or asks first while it is still running. */
  requestArchive: () => void;
  /** An archive request is in flight for this task. */
  isArchiving: boolean;
  /** Render once, wherever the surface that asked for it lives. */
  dialog: ReactElement;
}

/**
 * Archiving one open task, with the running-task confirm in front of it. Shared
 * by the surfaces that act on the task in view — its keyboard shortcut, its
 * header button, and the command menu — so all of them ask the same question and
 * report the same failure.
 *
 * The task is optional because the command menu outlives it: with no task open
 * there is nothing to archive, and `requestArchive` does nothing.
 */
export function useTaskArchive(
  task: Task | undefined,
  options?: {
    // Ignore the scoped space when the archived task is the active view,
    // landing on the unscoped new-task screen instead of the space's own.
    navigateUnscoped?: boolean;
  },
): TaskArchive {
  const taskId = task?.id;
  const { taskRunId, isPromptPending, cloudStatus, agentIdleForRunId } =
    useSessionSelector(
      taskId,
      (session) => ({
        taskRunId: session?.taskRunId,
        isPromptPending: session?.isPromptPending ?? false,
        cloudStatus: session?.cloudStatus ?? null,
        agentIdleForRunId: session?.agentIdleForRunId,
      }),
      shallow,
    );
  const piSessionController = useService<PiSessionController>(
    PI_SESSION_CONTROLLER,
  );
  const isPiGenerating = useStore(piSessionController.store, (state) =>
    taskId ? (state.sessions[taskId]?.status?.isStreaming ?? false) : false,
  );
  const sidebarTask = task ? narrowFullTask(task) : undefined;
  const taskRunState = sidebarTask
    ? deriveTaskRunState(
        sidebarTask,
        taskRunId
          ? {
              taskRunId,
              isPromptPending,
              cloudStatus: cloudStatus ?? undefined,
              agentIdleForRunId,
            }
          : undefined,
      )
    : undefined;
  const isGenerating =
    task?.runtime === "pi"
      ? isPiGenerating
      : (taskRunState?.isGenerating ?? false);

  const { archiveTask } = useArchiveTask({
    navigateUnscoped: options?.navigateUnscoped,
  });
  const isArchiving = useArchivingTasksStore((state) =>
    taskId ? state.archivingTaskIds.has(taskId) : false,
  );
  const [confirmOpen, setConfirmOpen] = useState(false);

  const runArchive = useCallback(async () => {
    if (!taskId) return;
    const store = useArchivingTasksStore.getState();
    if (store.isArchiving(taskId)) return;

    store.startArchiving(taskId);
    try {
      await archiveTask({ taskId });
    } catch (error) {
      log.error("Failed to archive task", error);
      toast.error("Failed to archive task");
      throw error;
    } finally {
      useArchivingTasksStore.getState().stopArchiving(taskId);
    }
  }, [archiveTask, taskId]);

  const requestArchive = useCallback(() => {
    if (!taskId) return;
    if (useArchivingTasksStore.getState().isArchiving(taskId)) return;
    if (
      isTaskActivelyRunning({
        isGenerating,
        runMode: sidebarTask?.latest_run?.mode ?? undefined,
        taskRunEnvironment: taskRunState?.taskRunEnvironment,
        taskRunStatus: taskRunState?.taskRunStatus,
      })
    ) {
      setConfirmOpen(true);
      return;
    }
    void runArchive().catch(() => undefined);
  }, [
    isGenerating,
    runArchive,
    sidebarTask?.latest_run?.mode,
    taskId,
    taskRunState?.taskRunEnvironment,
    taskRunState?.taskRunStatus,
  ]);

  return {
    requestArchive,
    isArchiving,
    dialog: (
      <ArchiveRunningTaskDialog
        open={confirmOpen}
        taskTitle={task?.title ?? ""}
        stopsCloudSandbox={task?.latest_run?.environment === "cloud"}
        onConfirm={async () => {
          try {
            await runArchive();
          } finally {
            setConfirmOpen(false);
          }
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    ),
  };
}
