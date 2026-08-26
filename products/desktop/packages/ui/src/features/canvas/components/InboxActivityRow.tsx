import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import { Avatar, AvatarFallback } from "@posthog/quill";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { ActivityRowSurface } from "@posthog/ui/features/canvas/components/ActivityRowSurface";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { type ReactElement, useState } from "react";

interface InboxActivityRowProps {
  report: SignalReport;
  onOpened?: () => void;
  compact?: boolean;
  asOption?: boolean;
  optionValue?: string;
  onActivate?: (report: SignalReport) => void;
  isSelected?: boolean;
}

export function InboxActivityRow({
  report,
  onOpened,
  compact = false,
  asOption = false,
  optionValue,
  onActivate,
  isSelected = false,
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

  const activate = (): void => {
    if (onActivate) {
      onActivate(report);
      onOpened?.();
      return;
    }
    void openReport();
  };

  return (
    <ActivityRowSurface
      type="button"
      asOption={asOption}
      optionValue={optionValue}
      onClick={activate}
      loading={!onActivate && isOpening}
      disabled={!onActivate && isOpening}
      aria-label={
        report.priority
          ? `${title} ${report.priority} Self-driving report`
          : `${title} Self-driving report`
      }
      left
      className={`${compact ? "py-1.5" : "py-2"} ${isSelected ? "bg-fill-selected" : ""}`}
    >
      <span className="mt-0.5 shrink-0">
        <Avatar
          size="xs"
          className={`bg-(--orange-3) text-(--orange-11) ring-(--orange-5) ring-1 ring-inset ${compact ? "size-4" : ""}`}
        >
          <AvatarFallback>
            <span className="font-bold text-[7px]">
              {report.priority ?? "–"}
            </span>
          </AvatarFallback>
        </Avatar>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-[13px]">{title}</span>
        <span className="block truncate text-muted-foreground text-xxs">
          {formatRelativeAge(report.updated_at)} · Self-driving
        </span>
      </span>
    </ActivityRowSurface>
  );
}
