import { buildCreateCanvasReportPrompt } from "@posthog/core/inbox/reportActions";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import type { Task } from "@posthog/shared/types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useCallback, useRef } from "react";

interface UseCreateCanvasReportOptions {
  reportId: string;
  reportTitle: string | null;
  /** The space that owns the report, when assigned; the agent falls back to #general. */
  channelId: string | null;
  cloudRepository: string | null;
  /** Fires once the canvas task exists so the report can open it in the dock. */
  onTaskCreated?: (task: Task) => void;
}

interface UseCreateCanvasReportReturn {
  /**
   * Start an auto-mode task that builds a canvas from the report's context into
   * its owning space. Every call starts a fresh build — multiple canvases per
   * report are fine, since each is user-initiated. A success toast offers
   * "View task" instead of navigating away.
   */
  createCanvasReport: (feedback?: string) => Promise<void>;
  /** True while the task is being created. */
  isCreatingCanvas: boolean;
}

export function useCreateCanvasReport({
  reportId,
  reportTitle,
  channelId,
  cloudRepository,
  onTaskCreated,
}: UseCreateCanvasReportOptions): UseCreateCanvasReportReturn {
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  // Same ref pattern as useCreatePrReport: `buildInput` runs synchronously
  // inside `run()`, so the ref is current when read and the callbacks stay stable.
  const feedbackRef = useRef<string | undefined>(undefined);

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => {
      const reportUrl =
        projectId != null
          ? buildPostHogUrl(
              `/project/${projectId}/inbox/${reportId}`,
              cloudRegion,
            )
          : null;
      const prompt = buildCreateCanvasReportPrompt({
        reportId,
        reportUrl,
        channelId,
        feedback: feedbackRef.current,
      });
      return {
        content: prompt,
        taskDescription: prompt,
        workspaceMode: "cloud",
        executionMode: "auto",
        adapter: ctx.adapter,
        model: ctx.model,
        reasoningLevel: ctx.reasoningLevel,
        cloudPrAuthorshipMode: "user",
        cloudRunSource: "signal_report",
        signalReportId: reportId,
        // A canvas build must not consume the report's one-live-PR gate.
        signalReportTaskRelationship: "canvas",
        // Files the build session in the target space so it shows in that
        // space's Sessions tab (the canvas itself lands there via the prompt).
        channelId: channelId ?? undefined,
      };
    },
    [reportId, channelId, cloudRegion, projectId],
  );

  const { run, isRunning } = useInboxCloudTaskRunner({
    reportId,
    reportTitle,
    cloudRepository,
    // The server resolves the repo from the report itself, same as Discuss; no
    // client-side repo gate applies to building a canvas.
    allowMissingRepository: true,
    loggerScope: "create-canvas-report",
    copy: {
      loadingTitle: "Starting canvas task...",
      successTitle: "Canvas task started",
      errorTitle: "Failed to start canvas task",
      missingRepository: "Pick a cloud repository before creating a canvas",
      missingIntegration: "Connect a GitHub integration to create a canvas",
      signedOut: "Sign in to create a canvas",
      missingModel:
        "Couldn't resolve a default model. Open the task page once and pick a model, then try again.",
    },
    buildInput,
    analyticsExtras: { has_branch: false },
    redirectOnSuccess: false,
    onTaskCreated,
  });

  const createCanvasReport = useCallback(
    async (feedback?: string) => {
      feedbackRef.current = feedback?.trim() || undefined;
      try {
        await run();
      } finally {
        feedbackRef.current = undefined;
      }
    },
    [run],
  );

  return { createCanvasReport, isCreatingCanvas: isRunning };
}
