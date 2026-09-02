import type { SignalReportPriority } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
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
}

export function SignalReportPriorityBadge({
  priority,
}: SignalReportPriorityBadgeProps): ReactNode {
  if (priority == null) {
    return null;
  }

  return (
    <InboxBadge variant={PRIORITY_VARIANT[priority]}>{priority}</InboxBadge>
  );
}
