import type {
  SignalActorKind,
  SignalReport,
  SignalReportWorkState,
} from "@posthog/shared/types";

/** An owner ready to render: who holds the report, and why that matters. */
export interface ReportOwnerDescription {
  kind: SignalActorKind;
  /** Short name for a chip or a row. */
  name: string;
  /** Longer sentence for a tooltip or a detail pane. */
  detail: string;
}

const WORK_STATE_LABELS: Record<SignalReportWorkState, string> = {
  unclaimed: "Unclaimed",
  working: "Working",
  in_review: "In review",
  done: "Done",
};

export function workStateLabel(state: SignalReportWorkState): string {
  return WORK_STATE_LABELS[state];
}

/**
 * The report's remediation state. The server sends `work_state`; reports served
 * before that field existed still carry the pull request fields, so derive an
 * equivalent state from those rather than showing the report as unclaimed.
 */
export function reportWorkState(report: SignalReport): SignalReportWorkState {
  if (report.work_state) return report.work_state;
  if (report.status === "resolved") return "done";
  if (report.implementation_pr_url && !report.implementation_pr_merged) {
    return "in_review";
  }
  return "unclaimed";
}

function userName(report: SignalReport): string {
  const user = report.assignee?.user;
  if (!user) return "A teammate";
  const full = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return full || user.email || "A teammate";
}

/**
 * Who is working on the report right now, or null when nobody has claimed it.
 * An external agent claims through the API and never appears as a cloud task,
 * so the two must read differently in the inbox.
 */
export function describeReportOwner(
  report: SignalReport,
): ReportOwnerDescription | null {
  const assignee = report.assignee;
  if (!assignee) return null;

  switch (assignee.kind) {
    case "user": {
      const name = userName(report);
      return { kind: "user", name, detail: `${name} claimed this report` };
    }
    case "task":
      return {
        kind: "task",
        name: "Cloud task",
        detail: "A PostHog cloud task is working on this report",
      };
    case "agent": {
      const name = assignee.agent?.trim() || "External agent";
      return {
        kind: "agent",
        name,
        detail: `${name} claimed this report from outside PostHog`,
      };
    }
    default:
      return {
        kind: "system",
        name: "PostHog",
        detail: "PostHog claimed this report automatically",
      };
  }
}

/**
 * Whether the inbox may offer Release. Only a claimed report can be released,
 * and a finished one has nothing left to hand back.
 */
export function canReleaseReport(report: SignalReport): boolean {
  return Boolean(report.assignee) && reportWorkState(report) !== "done";
}
