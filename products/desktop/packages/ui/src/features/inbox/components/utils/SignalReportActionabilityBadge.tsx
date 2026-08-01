import type { SignalReportActionability } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import type { ReactNode } from "react";

const ACTIONABILITY_STYLE: Record<
  SignalReportActionability,
  { variant: "success" | "warning" | "default"; label: string }
> = {
  immediately_actionable: { variant: "success", label: "Actionable" },
  requires_human_input: { variant: "warning", label: "Needs input" },
  not_actionable: { variant: "default", label: "Not actionable" },
};

interface SignalReportActionabilityBadgeProps {
  actionability: SignalReportActionability | null | undefined;
}

export function SignalReportActionabilityBadge({
  actionability,
}: SignalReportActionabilityBadgeProps): ReactNode {
  if (actionability == null) {
    return null;
  }

  const style = ACTIONABILITY_STYLE[actionability];
  if (!style) {
    return null;
  }

  return <InboxBadge variant={style.variant}>{style.label}</InboxBadge>;
}
