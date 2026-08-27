import { buildDiscussReportPrompt } from "@posthog/core/inbox/reportActions";
import { buildReportPromptContext } from "@posthog/core/inbox/reportPromptContext";
import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import type { SignalReport, Task } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

const log = logger.scope("discuss-report");

interface UseDiscussReportOptions {
  report: SignalReport;
  /** Space the created session belongs to (its feed home); null files it nowhere. */
  channelId?: string | null;
  /** Off for callers that show the conversation in place (the chat panel). */
  redirectOnSuccess?: boolean;
  /** Called with the created task, before any navigation. */
  onTaskCreated?: (task: Task) => void;
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
  channelId,
  redirectOnSuccess,
  onTaskCreated,
}: UseDiscussReportOptions): UseDiscussReportReturn {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();

  // Carry the per-invocation question + fetched context through to `buildInput`
  // (which runs synchronously inside `run()`). Refs, not state, so the
  // callbacks stay stable across question changes.
  const pendingQuestionRef = useRef<string | undefined>(undefined);
  const pendingContextRef = useRef<string | undefined>(undefined);
  // In-flight from the click, not just from `run()`: the evidence fetch happens
  // first, so without this the Discuss button reads idle during that request.
  // The ref is the synchronous re-entry guard; the state drives `isDiscussing`.
  const preparingRef = useRef(false);
  const [isPreparing, setIsPreparing] = useState(false);

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
        // Files the session in the report's space so it shows in that
        // space's Sessions tab; without it the task belongs to no space.
        channelId: channelId ?? undefined,
      };
    },
    [report, channelId],
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
    redirectOnSuccess,
    onTaskCreated,
  });

  const discussReport = useCallback(
    async (question?: string) => {
      // Ignore re-entry while a discussion is already being prepared or created.
      if (preparingRef.current) return;
      preparingRef.current = true;
      setIsPreparing(true);
      pendingQuestionRef.current = question;
      try {
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
        await run();
      } finally {
        pendingQuestionRef.current = undefined;
        pendingContextRef.current = undefined;
        preparingRef.current = false;
        setIsPreparing(false);
      }
    },
    [run, client, queryClient, report],
  );

  return { discussReport, isDiscussing: isRunning || isPreparing };
}
