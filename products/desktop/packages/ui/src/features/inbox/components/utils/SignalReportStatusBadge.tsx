import { inboxStatusLabel } from "@posthog/core/inbox/reportPresentation";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { SignalReportStatus } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";

type BadgeVariant = "success" | "info" | "warning" | "default" | "destructive";

const STATUS_META: Record<
  SignalReportStatus,
  { tooltip: string; variant: BadgeVariant }
> = {
  ready: {
    tooltip: "Research is complete. You can create a task from this report.",
    variant: "success",
  },
  resolved: { tooltip: "This report is resolved.", variant: "success" },
  monitoring: {
    tooltip: "Implementation is complete. Outcome verification is pending.",
    variant: "info",
  },
  closed: {
    tooltip: "This implementation attempt ended without proving resolution.",
    variant: "default",
  },
  pending_input: {
    tooltip: "This report needs human input in PostHog before it can proceed.",
    variant: "info",
  },
  in_progress: {
    tooltip: "An AI agent is actively researching this report's signals.",
    variant: "warning",
  },
  candidate: {
    tooltip: "Queued for research. An agent will pick this up shortly.",
    variant: "info",
  },
  potential: {
    tooltip:
      "Gathering signals. The report will be queued once enough evidence accumulates.",
    variant: "default",
  },
  failed: {
    tooltip: "Research failed. The report may be retried automatically.",
    variant: "destructive",
  },
  suppressed: {
    tooltip: "This report has been suppressed and is out of Self-driving.",
    variant: "default",
  },
  deleted: { tooltip: "This report has been deleted.", variant: "default" },
};

interface SignalReportStatusBadgeProps {
  status: SignalReportStatus;
}

export function SignalReportStatusBadge({
  status,
}: SignalReportStatusBadgeProps) {
  const meta = STATUS_META[status];
  return (
    <Tooltip>
      <TooltipTrigger
        render={<InboxBadge variant={meta.variant} className="cursor-help" />}
      >
        {inboxStatusLabel(status)}
      </TooltipTrigger>
      <TooltipContent>{meta.tooltip}</TooltipContent>
    </Tooltip>
  );
}
