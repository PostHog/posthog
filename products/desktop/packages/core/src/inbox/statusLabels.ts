import type { SignalReportStatus } from "@posthog/shared/domain-types";

export function inboxStatusLabel(status: SignalReportStatus): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "resolved":
      return "Resolved";
    case "pending_input":
      return "Needs input";
    case "in_progress":
      return "Researching";
    case "candidate":
      return "Queued";
    case "potential":
      return "Gathering";
    case "failed":
      return "Failed";
    case "suppressed":
      return "Suppressed";
    case "deleted":
      return "Deleted";
    default:
      return status;
  }
}
