import { DesktopIcon, GlobeIcon } from "@phosphor-icons/react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import type { ReactElement } from "react";

interface InboxReportCopyLinkMenuProps {
  report: SignalReport;
  trigger: ReactElement;
}

export function InboxReportCopyLinkMenu({
  report,
  trigger,
}: InboxReportCopyLinkMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="min-w-44"
      >
        <DropdownMenuItem
          data-attr="inbox-copy-web-link"
          onClick={() => copyInboxReportLink(report, "web")}
        >
          <GlobeIcon size={13} />
          Copy web link
        </DropdownMenuItem>
        <DropdownMenuItem
          data-attr="inbox-copy-desktop-link"
          onClick={() => copyInboxReportLink(report, "desktop")}
        >
          <DesktopIcon size={13} />
          Copy desktop link
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
