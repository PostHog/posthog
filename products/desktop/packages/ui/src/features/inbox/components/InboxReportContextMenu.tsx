import { ContextMenu, ContextMenuTrigger } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenuContent } from "@posthog/ui/features/inbox/components/InboxReportContextMenuContent";
import { type ReactNode, useState } from "react";

export function InboxReportContextMenu({
  report,
  children,
}: {
  report: SignalReport;
  children: ReactNode;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [activated, setActivated] = useState(false);
  return (
    <ContextMenu
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setActivated(true);
      }}
    >
      <ContextMenuTrigger render={<div className="min-w-0" />}>
        {children}
      </ContextMenuTrigger>
      {activated ? (
        <InboxReportContextMenuContent report={report} open={open} />
      ) : null}
    </ContextMenu>
  );
}
