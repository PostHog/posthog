import type { SignalReport } from "@posthog/shared/types";
import { InboxReportReadButton } from "@posthog/ui/features/inbox/components/InboxReportReadButton";
import { SelfDrivingReportListItem } from "@posthog/ui/features/inbox/components/SelfDrivingReportListItem";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
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
  const { isUnread } = useInboxReportReadState(report.id);
  const [isOpening, setIsOpening] = useState(false);

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
    <SelfDrivingReportListItem
      report={report}
      showKind
      ageFrom="updated_at"
      isSelected={isSelected}
      compact={compact}
      asOption={asOption}
      optionValue={optionValue}
      emphasized={isUnread}
      actions={<InboxReportReadButton reportId={report.id} />}
      actionCount={1}
      actionsVisibility="always"
      onClick={activate}
      loading={!onActivate && isOpening}
      disabled={!onActivate && isOpening}
    />
  );
}
