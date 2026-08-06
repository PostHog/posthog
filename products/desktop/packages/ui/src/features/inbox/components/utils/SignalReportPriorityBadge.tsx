import type { SignalReportPriority } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { priorityMeaningLine } from "@posthog/ui/features/inbox/filterOptions";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { ReactNode } from "react";

type BadgeVariant = "destructive" | "warning" | "default";

const PRIORITY_VARIANT: Record<SignalReportPriority, BadgeVariant> = {
  P0: "destructive",
  P1: "warning",
  P2: "warning",
  P3: "default",
  P4: "default",
};

interface SignalReportPriorityBadgeProps {
  priority: SignalReportPriority | null | undefined;
  /** Per-report rationale from the priority judgment artefact, when loaded. */
  explanation?: string | null;
}

export function SignalReportPriorityBadge({
  priority,
  explanation,
}: SignalReportPriorityBadgeProps): ReactNode {
  if (priority == null) {
    return null;
  }

  return (
    <Tooltip
      content={
        <span className="flex max-w-72 flex-col gap-1">
          <span className={explanation ? "font-semibold" : undefined}>
            {priorityMeaningLine(priority)}
          </span>
          {explanation ? <span>{explanation}</span> : null}
        </span>
      }
    >
      <span className="inline-flex cursor-help">
        <InboxBadge variant={PRIORITY_VARIANT[priority]}>{priority}</InboxBadge>
      </span>
    </Tooltip>
  );
}
