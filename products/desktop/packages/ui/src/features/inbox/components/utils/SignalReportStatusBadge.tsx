import { inboxStatusLabel } from "@posthog/core/inbox/reportPresentation";
import type { SignalReportStatus } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { Tooltip } from "@radix-ui/themes";

const STATUS_TOOLTIPS: Record<string, string> = {
  ready: "Research is complete. You can create a task from this report.",
  resolved: "This report is resolved — its implementation pull request merged.",
  pending_input:
    "This report needs human input in PostHog before it can proceed.",
  in_progress: "An AI agent is actively researching this report's findings.",
  candidate: "Queued for research. An agent will pick this up shortly.",
  potential:
    "Gathering findings. The report will be queued once enough evidence accumulates.",
  failed: "Research failed. The report may be retried automatically.",
  suppressed: "This report has been suppressed and is out of your inbox.",
  deleted: "This report has been deleted.",
};

type BadgeVariant = "success" | "info" | "warning" | "default" | "destructive";

function inboxStatusBadgeVariant(status: SignalReportStatus): BadgeVariant {
  switch (status) {
    case "ready":
      return "success";
    case "resolved":
      return "success";
    case "pending_input":
      return "info";
    case "in_progress":
      return "warning";
    case "candidate":
      return "info";
    case "failed":
      return "destructive";
    default:
      return "default";
  }
}

interface SignalReportStatusBadgeProps {
  status: SignalReportStatus;
}

export function SignalReportStatusBadge({
  status,
}: SignalReportStatusBadgeProps) {
  const label = inboxStatusLabel(status);
  const tooltip = STATUS_TOOLTIPS[status] ?? status;

  return (
    <Tooltip content={tooltip}>
      <InboxBadge
        variant={inboxStatusBadgeVariant(status)}
        className="cursor-help"
      >
        {label}
      </InboxBadge>
    </Tooltip>
  );
}
