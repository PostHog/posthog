import {
  personalInboxNextStepLabel,
  personalInboxReasonText,
} from "@posthog/core/inbox/reportPresentation";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { SignalReportPersonalInbox } from "@posthog/shared/types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import type { ReactNode } from "react";

/** The viewer's next step on a personal inbox row, with why the row is theirs. */
export function PersonalInboxNextStepBadge({
  personalInbox,
}: {
  personalInbox: SignalReportPersonalInbox | null | undefined;
}): ReactNode {
  const label = personalInboxNextStepLabel(personalInbox);
  if (!label) return null;
  const reason = personalInboxReasonText(personalInbox);
  const variant =
    personalInbox?.action_state === "action_available" ? "info" : "default";
  const badge = <InboxBadge variant={variant} className="cursor-help" />;

  if (!reason) {
    return <InboxBadge variant={variant}>{label}</InboxBadge>;
  }
  return (
    <Tooltip>
      <TooltipTrigger render={badge}>{label}</TooltipTrigger>
      <TooltipContent side="top">{reason}</TooltipContent>
    </Tooltip>
  );
}
