import { PopoverContent } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { InboxPane } from "@posthog/ui/features/inbox/components/InboxPane";
import { navigateToReport } from "@posthog/ui/router/navigationBridge";
import type { ReactElement } from "react";

interface InboxHoverCardProps {
  onClose: () => void;
  side?: "bottom" | "right";
}

export function InboxHoverCard({
  onClose,
  side = "right",
}: InboxHoverCardProps): ReactElement {
  const openReport = (report: SignalReport): void => {
    navigateToReport(report.id, { sourceHref: "/inbox" });
    onClose();
  };

  return (
    <PopoverContent
      side={side}
      align="start"
      sideOffset={8}
      className="max-h-[520px] w-[380px] gap-0 overflow-hidden p-0"
    >
      <InboxPane className="max-h-[520px]" onReportActivate={openReport} />
    </PopoverContent>
  );
}
