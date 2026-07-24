import { buildDiscussReportPrompt } from "@posthog/core/inbox/reportActions";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useCallback, useRef } from "react";

interface UseDiscussReportOptions {
  reportId: string;
  reportTitle: string | null;
  cloudRepository: string | null;
}

interface UseDiscussReportReturn {
  /** Create a Discuss task for the report and navigate to it on success. */
  discussReport: (question?: string) => Promise<void>;
  /** True while a Discuss task is being created. */
  isDiscussing: boolean;
}

export function useDiscussReport({
  reportId,
  reportTitle,
  cloudRepository,
}: UseDiscussReportOptions): UseDiscussReportReturn {
  // Carry the per-invocation question through to `buildInput`. A ref (not
  // state) so `discussReport`'s identity stays stable across question changes.
  const pendingQuestionRef = useRef<string | undefined>(undefined);

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => {
      const prompt = buildDiscussReportPrompt({
        reportId,
        reportTitle,
        question: pendingQuestionRef.current,
        isDevBuild: import.meta.env.DEV,
      });
      return {
        content: prompt,
        taskDescription: prompt,
        repository: ctx.cloudRepository,
        githubUserIntegrationId: ctx.githubUserIntegrationId ?? undefined,
        workspaceMode: "cloud",
        executionMode: "auto",
        adapter: ctx.adapter,
        model: ctx.model,
        reasoningLevel: ctx.reasoningLevel,
        cloudPrAuthorshipMode: "user",
        cloudRunSource: "signal_report",
        signalReportId: reportId,
      };
    },
    [reportId, reportTitle],
  );

  const { run, isRunning } = useInboxCloudTaskRunner({
    reportId,
    reportTitle,
    cloudRepository,
    loggerScope: "discuss-report",
    copy: {
      loadingTitle: "Starting discussion...",
      errorTitle: "Failed to start discussion",
      missingRepository: "Pick a cloud repository before starting a discussion",
      missingIntegration: "Connect a GitHub integration to start a discussion",
      signedOut: "Sign in to start a discussion",
      missingModel:
        "Couldn't resolve a default model. Open the task page once and pick a model, then try again.",
    },
    buildInput,
    analyticsExtras: { has_branch: false },
  });

  const discussReport = useCallback(
    async (question?: string) => {
      pendingQuestionRef.current = question;
      try {
        await run();
      } finally {
        pendingQuestionRef.current = undefined;
      }
    },
    [run],
  );

  return { discussReport, isDiscussing: isRunning };
}
