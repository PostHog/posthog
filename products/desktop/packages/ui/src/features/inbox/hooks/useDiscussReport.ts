import { buildDiscussReportPrompt } from "@posthog/core/inbox/reportActions";
import { buildReportPromptContext } from "@posthog/core/inbox/reportPromptContext";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";

const log = logger.scope("discuss-report");

interface UseDiscussReportOptions {
  report: SignalReport;
}

interface UseDiscussReportReturn {
  /** Create a Discuss task for the report and navigate to it on success. */
  discussReport: (question?: string) => Promise<void>;
  /** True while a Discuss task is being created. */
  isDiscussing: boolean;
}

/** Short task description: it feeds the task list row and title generation. */
function buildDiscussDescription(
  report: SignalReport,
  question: string | undefined,
): string {
  const title = report.title?.trim() || report.id;
  const base = `Discuss report: ${title}`;
  const trimmed = question?.trim();
  return trimmed ? `${base} — ${trimmed}`.slice(0, 200) : base.slice(0, 200);
}

/**
 * "Discuss" on a report: start an auto-mode cloud session whose first message
 * carries the whole report (summary + evidence) plus the user's question. The
 * repository is deliberately not sent — signal-report tasks resolve it
 * server-side from the report's own repo selection, and the backend rejects a
 * client-set repo — so a discussion also starts on reports with no repo at all
 * (bare sandbox + PostHog MCP).
 */
export function useDiscussReport({
  report,
}: UseDiscussReportOptions): UseDiscussReportReturn {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();

  // Carry the per-invocation question + fetched context through to `buildInput`
  // (which runs synchronously inside `run()`). Refs, not state, so the
  // callbacks stay stable across question changes.
  const pendingQuestionRef = useRef<string | undefined>(undefined);
  const pendingContextRef = useRef<string | undefined>(undefined);

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => {
      const question = pendingQuestionRef.current;
      const prompt = buildDiscussReportPrompt({
        reportId: report.id,
        reportTitle: report.title ?? null,
        question,
        isDevBuild: import.meta.env.DEV,
        reportContext: pendingContextRef.current,
      });
      return {
        // The first message the agent sees: question + inlined report.
        content: prompt,
        // Kept short — this is the task record, not the prompt.
        taskDescription: buildDiscussDescription(report, question),
        workspaceMode: "cloud",
        executionMode: "auto",
        adapter: ctx.adapter,
        model: ctx.model,
        reasoningLevel: ctx.reasoningLevel,
        cloudPrAuthorshipMode: "user",
        cloudRunSource: "signal_report",
        signalReportId: report.id,
        // Routes the per-report cap: a discussion must not consume the
        // report's one-live-implementation (PR) gate.
        signalReportTaskRelationship: "discussion",
      };
    },
    [report],
  );

  const { run, isRunning } = useInboxCloudTaskRunner({
    reportId: report.id,
    reportTitle: report.title ?? null,
    // The server resolves the repo from the report itself; no client-side repo
    // or GitHub-integration gate applies to starting a discussion.
    cloudRepository: null,
    allowMissingRepository: true,
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
      // Inline the report's evidence into the first message. The signals query
      // is usually already cached by the detail page's Evidence section; a
      // fetch failure degrades to summary-only context, never blocks the
      // discussion.
      let context: string;
      try {
        const signalsResp = client
          ? await queryClient.fetchQuery({
              queryKey: reportKeys.signals(report.id),
              queryFn: () => client.getSignalReportSignals(report.id),
              meta: AUTH_SCOPED_QUERY_META,
            })
          : null;
        context = buildReportPromptContext(
          signalsResp?.report ?? report,
          signalsResp?.signals ?? [],
        );
      } catch (error) {
        log.warn("Failed to fetch report signals; inlining summary only", {
          reportId: report.id,
          error,
        });
        context = buildReportPromptContext(report, []);
      }
      pendingContextRef.current = context;
      try {
        await run();
      } finally {
        pendingQuestionRef.current = undefined;
        pendingContextRef.current = undefined;
      }
    },
    [run, client, queryClient, report],
  );

  return { discussReport, isDiscussing: isRunning };
}
