import type { SignalReport } from "@posthog/shared/types";

/** Drives the banner's styling: what kind of moment the report is in. */
export type ReportVerdictTone = "decision" | "progress" | "info" | "danger";

export interface ReportVerdict {
  tone: ReportVerdictTone;
  /** The state line a reader scans first, e.g. "Needs your decision". */
  title: string;
  /** One or two sentences: why the report is in this state and what to do. */
  body: string;
}

/**
 * What a report is asking of its reader, stated before the prose. The detail
 * page leads with this so the decision doesn't hide at the bottom of a long
 * summary; the banner component adds the matching action buttons beside it.
 *
 * `hasExistingPr` folds in what the report row alone can't know: a linked
 * implementation task may hold a live PR before `implementation_pr_url` is
 * stamped (see findContinuableImplementationTask).
 */
export function deriveReportVerdict(
  report: SignalReport,
  { hasExistingPr }: { hasExistingPr: boolean },
): ReportVerdict {
  switch (report.status) {
    case "resolved":
      return {
        tone: "info",
        title: "Resolved",
        body: "This report is resolved. Nothing left to do here.",
      };
    case "suppressed":
    case "deleted":
      return {
        tone: "info",
        title: "Archived",
        body: "This report was archived and is kept for reference.",
      };
    case "failed":
      return {
        tone: "danger",
        title: "Run failed",
        body: "The agent couldn't finish this report. Archive it, or start a chat to dig into what happened.",
      };
    case "pending_input":
      return {
        tone: "decision",
        title: "Waiting on you",
        body: "The agent needs your input before it can continue.",
      };
    case "potential":
    case "candidate":
    case "in_progress":
      return {
        tone: "progress",
        title: "Agent investigating",
        body: "The agent is still gathering evidence. This report updates as findings land.",
      };
    case "ready":
      break;
  }

  if (hasExistingPr) {
    return {
      tone: "decision",
      title: "Review the open PR",
      body: "Implementation is already in flight. Review the pull request, or continue the task that opened it — new work lands on the same branch.",
    };
  }
  if (report.already_addressed) {
    return {
      tone: "info",
      title: "Likely already fixed",
      body: "The evidence suggests this was already addressed. Skim the summary and archive the report if you agree.",
    };
  }
  switch (report.actionability) {
    case "immediately_actionable":
      return {
        tone: "decision",
        title: "Needs your decision",
        body: "The agent can fix this with code and open a pull request. The report keeps watching its signals and reopens if the problem comes back.",
      };
    case "requires_human_input":
      return {
        tone: "decision",
        title: "Needs your direction",
        body: "A fix needs your call first: business context, trade-offs, or a choice between approaches. Add direction when you start the PR, or ask about it in chat.",
      };
    case "not_actionable":
      return {
        tone: "info",
        title: "For your awareness",
        body: "No code change follows from this report. Read it, then archive it.",
      };
    default:
      return {
        tone: "decision",
        title: "Ready for review",
        body: "Read the summary and decide what happens next.",
      };
  }
}
