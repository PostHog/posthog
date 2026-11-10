import {
  buildCreatePrReportPrompt,
  implementationClaimStep,
} from "@posthog/core/inbox/reportActions";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import type { SignalReport, Task } from "@posthog/shared/types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import {
  ImplementClaimDialog,
  type ImplementClaimDialogStep,
} from "@posthog/ui/features/inbox/components/ImplementClaimDialog";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useSignalTeamConfig } from "@posthog/ui/features/inbox/hooks/useSignalTeamConfig";
import { useTakeOverReportClaim } from "@posthog/ui/features/inbox/hooks/useTakeOverReportClaim";
import { toast } from "@posthog/ui/primitives/toast";
import {
  type ReactElement,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";

interface UseCreatePrReportOptions {
  reportId: string;
  reportTitle: string | null;
  cloudRepository: string | null;
  /** Who holds the report decides whether Create PR asks first or takes over a claim. */
  claim?: Pick<SignalReport, "assignee" | "implementation_in_flight">;
  surface?: InboxReportActionSurface;
  triageId?: string;
  /** Fires after the implementation task starts successfully. */
  onTaskCreated?: (task: Task) => void;
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
  /** The confirmation Create PR is waiting on, to render next to the trigger. */
  claimDialog: ReactElement | null;
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
  claim,
  surface = "detail_pane",
  triageId,
  onTaskCreated,
}: UseCreatePrReportOptions): UseCreatePrReportReturn {
  const { data: currentUser } = useMeQuery();
  const takeOver = useTakeOverReportClaim();
  const [pending, setPending] = useState<{
    step: ImplementClaimDialogStep;
    feedback?: string;
  } | null>(null);
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

  const { run, isRunning, checkPrerequisites } = useInboxCloudTaskRunner({
    reportId,
    reportTitle,
    reportAction: {
      action_type: "create_pr",
      surface,
      ...(triageId ? { triage_id: triageId } : {}),
    },
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
      existingImplementationTask:
        "This report already has an implementation task. Open it from the activity section to continue.",
    },
    buildInput,
    analyticsExtras,
    redirectOnSuccess: false,
    onTaskStarted: onTaskCreated,
  });

  const start = useCallback(
    async (feedback?: string) => {
      feedbackRef.current = feedback?.trim() || undefined;
      await run();
    },
    [run],
  );

  const createPrReport = useCallback(
    async (feedback?: string) => {
      const step = implementationClaimStep(claim ?? {}, currentUser?.uuid);
      if (step.kind === "blocked") {
        toast.error("Failed to start PR task", { description: step.reason });
        return;
      }
      if (step.kind === "start") {
        await start(feedback);
        return;
      }
      // A takeover moves the claim and notifies the holder, so it must not
      // happen for a run that would then fail its own checks.
      if (!checkPrerequisites()) return;
      setPending({ step, feedback });
    },
    [claim, currentUser?.uuid, start, checkPrerequisites],
  );

  const confirmPending = useCallback(async () => {
    if (!pending) return;
    if (pending.step.kind === "take_over") {
      try {
        await takeOver.mutateAsync({
          reportId,
          claimId: pending.step.claimId,
        });
      } catch {
        // A confirmed takeover does not retry: the claim may now belong to
        // someone the user did not confirm.
        setPending(null);
        toast.error("Couldn't take over this report", {
          description: "It may have changed. Refresh it and try again.",
        });
        return;
      }
    }
    setPending(null);
    await start(pending.feedback);
  }, [pending, reportId, start, takeOver]);

  const claimDialog = pending ? (
    <ImplementClaimDialog
      step={pending.step}
      isSubmitting={takeOver.isPending}
      onConfirm={() => void confirmPending()}
      onCancel={() => setPending(null)}
    />
  ) : null;

  return {
    createPrReport,
    isCreatingPr: isRunning || takeOver.isPending,
    claimDialog,
  };
}
