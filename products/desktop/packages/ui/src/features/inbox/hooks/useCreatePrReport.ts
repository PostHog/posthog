import { buildCreatePrReportPrompt } from "@posthog/core/inbox/reportActions";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useSignalTeamConfig } from "@posthog/ui/features/inbox/hooks/useSignalTeamConfig";
import { useCallback, useMemo, useRef } from "react";

interface UseCreatePrReportOptions {
  reportId: string;
  reportTitle: string | null;
  cloudRepository: string | null;
}

interface UseCreatePrReportReturn {
  /**
   * Create an auto-mode implementation task for the report. Adds the task to the
   * sidebar and surfaces a success toast with a "View task" action instead of
   * navigating away.
   *
   * `feedback` is optional free-text steering passed straight into the agent's
   * prompt, so the user can give direction at Create-PR time instead of waiting
   * for the run and correcting it after the fact.
   */
  createPrReport: (feedback?: string) => Promise<void>;
  /** True while the task is being created. */
  isCreatingPr: boolean;
}

/**
 * Create an implementation (PR) task directly from the inbox detail pane.
 *
 * Bypasses TaskInput so the user stays on the inbox until the task is ready.
 * Rather than navigating away, the task is added to the sidebar and a success
 * toast offers a "View task" action to open the task detail page on demand. The
 * agent receives a short prompt pointing it at the inbox MCP tools instead of
 * inlining the report summary. The base branch comes from the team-level
 * autostart override map.
 */
export function useCreatePrReport({
  reportId,
  reportTitle,
  cloudRepository,
}: UseCreatePrReportOptions): UseCreatePrReportReturn {
  const { data: teamConfig } = useSignalTeamConfig();
  const baseBranchOverrides = teamConfig?.autostart_base_branches ?? null;
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  // Holds the steering text for the in-flight run. `buildInput` is invoked
  // synchronously inside `run()`, so the ref is always current when read; a ref
  // (vs state) keeps `buildInput`/`run` stable and avoids a re-render race.
  const feedbackRef = useRef<string | undefined>(undefined);

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => {
      // Web URL rather than a `posthog-code://` deep link: the prompt runs in a
      // cloud task and may be echoed into the PR, where only an https link works.
      const reportUrl =
        projectId != null
          ? buildPostHogUrl(
              `/project/${projectId}/inbox/${reportId}`,
              cloudRegion,
            )
          : null;
      const prompt = buildCreatePrReportPrompt({
        reportId,
        reportUrl,
        feedback: feedbackRef.current,
      });
      // Create-PR never runs repo-less, so the repo is always present here; the
      // coalesce only satisfies the now-nullable context type.
      const targetRepo = (ctx.cloudRepository ?? "").toLowerCase();
      const baseBranch = baseBranchOverrides
        ? (Object.entries(baseBranchOverrides).find(
            ([repo]) => repo.toLowerCase() === targetRepo,
          )?.[1] ?? null)
        : null;
      return {
        content: prompt,
        taskDescription: prompt,
        repository: ctx.cloudRepository,
        githubUserIntegrationId: ctx.githubUserIntegrationId ?? undefined,
        workspaceMode: "cloud",
        executionMode: "auto",
        adapter: ctx.adapter,
        model: ctx.model,
        branch: baseBranch,
        reasoningLevel: ctx.reasoningLevel,
        cloudPrAuthorshipMode: "user",
        cloudRunSource: "signal_report",
        signalReportId: reportId,
      };
    },
    [baseBranchOverrides, reportId, cloudRegion, projectId],
  );

  const analyticsExtras = useMemo(
    () => ({
      has_branch:
        baseBranchOverrides != null &&
        cloudRepository != null &&
        Object.keys(baseBranchOverrides).some(
          (repo) => repo.toLowerCase() === cloudRepository.toLowerCase(),
        ),
    }),
    [baseBranchOverrides, cloudRepository],
  );

  const { run, isRunning } = useInboxCloudTaskRunner({
    reportId,
    reportTitle,
    cloudRepository,
    loggerScope: "create-pr-report",
    copy: {
      loadingTitle: "Starting PR task...",
      successTitle: "PR task started",
      errorTitle: "Failed to start PR task",
      missingRepository: "Pick a cloud repository before creating a PR",
      missingIntegration: "Connect a GitHub integration to create a PR",
      signedOut: "Sign in to create a PR",
      missingModel:
        "Couldn't resolve a default model. Open the task page once and pick a model, then try again.",
    },
    buildInput,
    analyticsExtras,
    redirectOnSuccess: false,
  });

  const createPrReport = useCallback(
    async (feedback?: string) => {
      feedbackRef.current = feedback?.trim() || undefined;
      await run();
    },
    [run],
  );

  return { createPrReport, isCreatingPr: isRunning };
}
