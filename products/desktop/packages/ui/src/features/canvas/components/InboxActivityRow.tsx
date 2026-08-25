import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import { Avatar, AvatarFallback, Button } from "@posthog/quill";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { type ReactElement, useState } from "react";

interface InboxActivityRowProps {
  report: SignalReport;
  onOpened?: () => void;
  compact?: boolean;
}

export function InboxActivityRow({
  report,
  onOpened,
  compact = false,
}: InboxActivityRowProps): ReactElement {
  const openInboxReport = useOpenInboxReport();
  const [isOpening, setIsOpening] = useState(false);
  const title = humanizeReportTitle(report.title, "Untitled report");

  const openReport = async (): Promise<void> => {
    if (isOpening) return;
    setIsOpening(true);
    try {
      await openInboxReport(report.id);
      onOpened?.();
    } finally {
      setIsOpening(false);
    }
  };

  return (
    <Button
      type="button"
      onClick={() => void openReport()}
      loading={isOpening}
      disabled={isOpening}
      aria-label={`${title} P1 Self-driving report`}
      left
      className={`h-auto w-full items-start text-left ${compact ? "py-1.5" : "py-2"}`}
    >
      <span className="mt-0.5 shrink-0">
        <Avatar
          size="xs"
          className={`bg-(--orange-3) text-(--orange-11) ring-(--orange-5) ring-1 ring-inset ${compact ? "size-4" : ""}`}
        >
          <AvatarFallback>
            <span className="font-bold text-[7px]">P1</span>
          </AvatarFallback>
        </Avatar>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-[13px]">{title}</span>
        <span className="block truncate text-muted-foreground text-xxs">
          {formatRelativeAge(report.updated_at)} · Self-driving
        </span>
      </span>
    </Button>
  );
}
