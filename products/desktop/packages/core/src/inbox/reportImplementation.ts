import type { SignalReport, Task } from "@posthog/shared/types";

export type ReportImplementationState =
  | "checking"
  | "working"
  | "needs_input"
  | "failed"
  | "cancelled"
  | "no_pr"
  | "in_review"
  | "unknown";

export const REPORT_IMPLEMENTATION_LABELS: Record<
  ReportImplementationState,
  string
> = {
  checking: "Checking task status",
  working: "Creating PR",
  needs_input: "Waiting on you",
  failed: "PR task failed",
  cancelled: "PR task stopped",
  no_pr: "No PR created",
  in_review: "PR created",
  unknown: "Task status unavailable",
};

export function reportImplementationTaskId(
  report: SignalReport,
): string | null {
  if (report.implementation_pr_url && !report.implementation_pr_merged)
    return null;
  if (
    report.status === "resolved" ||
    report.status === "suppressed" ||
    report.status === "deleted"
  )
    return null;
  return report.assignee?.kind === "task" ? report.assignee.task_id : null;
}

export function deriveReportImplementationState(
  report: SignalReport,
  task:
    | {
        latest_run?: {
          status: string | null;
          output?: NonNullable<Task["latest_run"]>["output"];
        } | null;
      }
    | undefined,
  lookupFailed = false,
): ReportImplementationState | null {
  if (!reportImplementationTaskId(report)) return null;
  if (report.status === "pending_input") return "needs_input";
  if (lookupFailed) return "unknown";
  if (!task) return "checking";
  const run = task.latest_run;
  if (run?.status === "failed") return "failed";
  if (run?.status === "cancelled") return "cancelled";
  const prClosed =
    report.implementation_pr_merged ||
    run?.output?.pr_merged === true ||
    run?.output?.pr_state === "merged" ||
    run?.output?.pr_state === "closed";
  if (
    !prClosed &&
    (report.implementation_pr_url ||
      (typeof run?.output?.pr_url === "string" && run.output.pr_url.trim()))
  )
    return "in_review";
  if (!run) return "unknown";
  if (run.status === "completed") return "no_pr";
  return run.status === "not_started" ||
    run.status === "queued" ||
    run.status === "in_progress"
    ? "working"
    : "unknown";
}

export function needsImplementationDecision(
  state: ReportImplementationState | null,
): boolean {
  return state !== "working" && state !== "in_review" && state !== "checking";
}
