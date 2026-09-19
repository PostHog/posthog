import type { IconProps } from "@phosphor-icons/react";
import {
  humanizeReportTitle,
  parseConventionalCommitTitle,
} from "@posthog/core/inbox/reportPresentation";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { InboxMetaRow } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { ReportBreadcrumbs } from "@posthog/ui/features/inbox/components/ReportBreadcrumbs";
import { ReportDetailCloseButton } from "@posthog/ui/features/inbox/components/ReportDetailCloseButton";
import { useReportPage } from "@posthog/ui/features/inbox/components/ReportPageContext";
import { ReportSummaryDocument } from "@posthog/ui/features/inbox/components/ReportSummaryDocument";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { ComponentType, ReactNode } from "react";
import { useMemo, useState } from "react";

export interface InboxDetailFrameViewProps {
  report: SignalReport;
  fallbackTitle: string;
  breadcrumb?: ReactNode;
  metaPrefix?: ReactNode;
  metaSuffix?: ReactNode;
  primaryAction?: ReactNode;
  aboveSummary?: ReactNode;
  summarySection: { Icon: ComponentType<IconProps>; title: string };
  belowSummary?: ReactNode;
  footer?: ReactNode;
  evidenceSection: {
    Icon: ComponentType<IconProps>;
    title: string;
  } | null;
  evidenceCount: number;
  evidenceContent?: ReactNode;
  aboveEvidence?: ReactNode;
  secondaryTab?: { label: ReactNode; content: ReactNode };
  dismissButton?: ReactNode;
  dismissDialog?: ReactNode;
  showMetadata?: boolean;
  children?: ReactNode;
}

export function InboxDetailFrameView({
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
  evidenceCount,
  evidenceContent,
  aboveEvidence,
  secondaryTab,
  dismissButton,
  dismissDialog,
  showMetadata = true,
  children,
}: InboxDetailFrameViewProps): React.JSX.Element {
  const [activeTab, setActiveTab] = useState("overview");
  const ownsChrome = useReportPage() !== null;
  const EvidenceIcon = evidenceSection?.Icon;
  const hasEvidence =
    evidenceSection != null && EvidenceIcon != null && evidenceCount > 0;
  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const displayTitle = humanizeReportTitle(report.title, fallbackTitle);
  const title = (
    <>
      {conventionalTitle && (
        <ConventionalCommitScopeTag
          type={conventionalTitle.type}
          scope={conventionalTitle.scope}
        />
      )}
      {displayTitle}
    </>
  );

  const reportMeta = (
    <>
      {metaPrefix}
      <RelativeTimestamp
        timestamp={report.updated_at ?? report.created_at}
        className="text-[13px]"
      />
      {metaSuffix}
    </>
  );

  const trail = useMemo(
    () => (
      <div className="flex min-w-0 flex-1 items-center gap-2 text-[13px] text-gray-11">
        <ReportBreadcrumbs report={report} />
        {breadcrumb}
      </div>
    ),
    [report, breadcrumb],
  );
  const actions = useMemo(
    () => (
      <>
        {primaryAction}
        {dismissButton}
        {ownsChrome && <ReportDetailCloseButton />}
      </>
    ),
    [primaryAction, dismissButton, ownsChrome],
  );
  const header = useMemo(
    () => (
      <>
        {trail}
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      </>
    ),
    [trail, actions],
  );
  useSetHeaderContent(header, ownsChrome);

  return (
    <div className="@container flex min-h-full flex-col">
      {!ownsChrome && (
        <ChromeBar inset="control" actions={actions}>
          {trail}
        </ChromeBar>
      )}

      <div className="mx-auto w-full max-w-[calc(160ch+5rem)]">
        <div className="flex @5xl:flex-row flex-col @5xl:items-start overflow-hidden">
          <main className="@5xl:order-none order-1 flex min-w-0 flex-1 flex-col">
            <Tabs
              value={secondaryTab ? activeTab : "overview"}
              onValueChange={setActiveTab}
            >
              <TabsList
                variant="line"
                className="h-auto w-full justify-start gap-0.5 border-border border-b"
              >
                <TabsTrigger value="overview" className="gap-1.5 px-2.5 py-2">
                  <span className="font-bold text-[14px]">
                    {summarySection.title}
                  </span>
                </TabsTrigger>
                {secondaryTab && (
                  <TabsTrigger
                    value="secondary"
                    className="gap-1.5 px-2.5 py-2"
                  >
                    <span className="flex items-center gap-1.5 font-medium text-[14px]">
                      {secondaryTab.label}
                    </span>
                  </TabsTrigger>
                )}
              </TabsList>
            </Tabs>

            {secondaryTab && activeTab === "secondary" ? (
              <div className="flex min-w-0 flex-col gap-5 p-4">
                <h1 className="m-0 min-w-0 font-bold text-[24px] text-gray-12 leading-tight tracking-tight">
                  {title}
                </h1>
                {secondaryTab.content}
              </div>
            ) : (
              <div className="flex min-h-full min-w-0 flex-col gap-6 p-4">
                <div className="flex flex-col gap-2">
                  <h1 className="m-0 min-w-0 font-bold text-[24px] text-gray-12 leading-tight tracking-tight">
                    {title}
                  </h1>
                  {showMetadata && (
                    <div className="flex flex-wrap items-center gap-2">
                      {report.status !== "ready" && (
                        <SignalReportStatusBadge status={report.status} />
                      )}
                      <InboxMetaRow>{reportMeta}</InboxMetaRow>
                    </div>
                  )}
                </div>
                {aboveSummary}
                <ReportSummaryDocument report={report} />
                {belowSummary}
              </div>
            )}
          </main>
          <aside className="@5xl:order-none order-2 flex @5xl:w-[26rem] w-full min-w-0 @5xl:shrink-0 flex-col gap-2 @5xl:self-stretch p-2">
            {hasEvidence && (
              <RightColumnSection
                Icon={EvidenceIcon}
                title={evidenceSection.title}
                collapsible
                rightSlot={
                  <span className="cursor-default select-none text-[12px] text-gray-10 tabular-nums">
                    {evidenceCount} signal{evidenceCount === 1 ? "" : "s"}
                  </span>
                }
              >
                {evidenceContent}
              </RightColumnSection>
            )}
            {aboveEvidence}
            {children}
          </aside>
        </div>
        {footer && (!secondaryTab || activeTab === "overview") && (
          <div className="mx-4 mt-4 border-border border-t py-4">{footer}</div>
        )}
        {dismissDialog}
      </div>
    </div>
  );
}
