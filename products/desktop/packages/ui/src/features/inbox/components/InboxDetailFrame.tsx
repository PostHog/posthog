import type { IconProps } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import {
  SignalsList,
  SignalsListSkeleton,
} from "@posthog/ui/features/inbox/components/SignalsList";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
import { useInboxReportSignals } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { type ComponentType, type ReactNode, useEffect } from "react";

interface InboxDetailFrameProps {
  report: SignalReport;
  showDismiss?: boolean;
  showMetadata?: boolean;
  fallbackTitle: string;
  breadcrumb?: ReactNode;
  metaPrefix?: ReactNode;
  metaSuffix?: ReactNode;
  primaryAction?: ReactNode;
  aboveSummary?: ReactNode;
  summarySection: {
    Icon: ComponentType<IconProps>;
    title: string;
  };
  belowSummary?: ReactNode;
  footer?: ReactNode;
  evidenceSection: {
    Icon: ComponentType<IconProps>;
    title: string;
  } | null;
  aboveEvidence?: ReactNode;
  secondaryTab?: { label: ReactNode; content: ReactNode };
  children?: ReactNode;
}

export function InboxDetailFrame({
  report,
  fallbackTitle,
  breadcrumb,
  metaPrefix,
  metaSuffix,
  primaryAction,
  aboveSummary,
  summarySection,
  belowSummary,
  footer,
  evidenceSection,
  aboveEvidence,
  secondaryTab,
  showDismiss = true,
  showMetadata = true,
  children,
}: InboxDetailFrameProps): React.JSX.Element {
  const { enabled: readStateEnabled, setRead } = useInboxReportReadState(
    report.id,
  );
  useEffect(() => {
    if (readStateEnabled) setRead(true);
  }, [readStateEnabled, setRead]);
  const { data: signalsResp } = useInboxReportSignals(report.id);
  const signals = signalsResp?.signals ?? [];
  const signalsLoaded = signalsResp !== undefined;
  const { actionButton: dismissButton, dialog: dismissDialog } =
    useInboxReportDismissAction(report);

  const evidenceUnavailable =
    signalsLoaded && signalsResp?.report === null && report.signal_count > 0;
  const evidenceCount =
    !signalsLoaded || evidenceUnavailable
      ? report.signal_count
      : signals.length;
  const evidenceContent = evidenceUnavailable ? (
    <p className="m-0 text-[13px] text-gray-10">
      Couldn't load the evidence for this report. Reopen the report to try
      again.
    </p>
  ) : signals.length > 0 ? (
    <SignalsList signals={signals} />
  ) : (
    <SignalsListSkeleton count={evidenceCount} />
  );

  return (
    <InboxDetailFrameView
      report={report}
      fallbackTitle={fallbackTitle}
      breadcrumb={breadcrumb}
      metaPrefix={metaPrefix}
      metaSuffix={metaSuffix}
      primaryAction={primaryAction}
      aboveSummary={aboveSummary}
      summarySection={summarySection}
      belowSummary={belowSummary}
      footer={footer}
      evidenceSection={evidenceSection}
      evidenceCount={evidenceCount}
      evidenceContent={evidenceContent}
      aboveEvidence={aboveEvidence}
      secondaryTab={secondaryTab}
      showMetadata={showMetadata}
      dismissButton={showDismiss ? dismissButton : undefined}
      dismissDialog={showDismiss ? dismissDialog : undefined}
    >
      {children}
    </InboxDetailFrameView>
  );
}
