import type { SignalReport } from "@posthog/shared/types";

/** Explain the server's existing work-state decision; do not rank or filter again in the client. */
export function recommendationPresentation(report: SignalReport) {
  if (
    report.implementation_pr_state === "open" &&
    report.implementation_pr_url
  ) {
    return {
      action: "Review PR",
      reason: "A pull request is ready to review.",
    };
  }
  if (report.actionability === "requires_human_input") {
    return {
      action: "Answer question",
      reason: "This report needs human input.",
    };
  }
  return {
    action: "Investigate",
    reason: "This report is actionable and no one has claimed it.",
  };
}
