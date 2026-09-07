import type { IconProps } from "@phosphor-icons/react";
import {
  humanizeReportTitle,
  parseConventionalCommitTitle,
} from "@posthog/core/inbox/reportPresentation";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { DetailBackLink } from "@posthog/ui/features/inbox/components/DetailBackLink";
import {
  InboxMetaRow,
  InboxMetaSeparator,
  InboxMetaText,
} from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { ReportSummaryDocument } from "@posthog/ui/features/inbox/components/ReportSummaryDocument";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import type { InboxListRoute } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { ComponentType, ReactNode } from "react";
import { useState } from "react";

export interface InboxDetailFrameViewProps {
  report: SignalReport;
  backTo: InboxListRoute | (string & {});
  backLabel: string;
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
  runRepository?: string | null;
  aboveEvidence?: ReactNode;
  secondaryTab?: { label: ReactNode; content: ReactNode };
  dismissButton?: ReactNode;
  dismissDialog?: ReactNode;
  showMetadata?: boolean;
  children?: ReactNode;
}

export function InboxDetailFrameView({
  report,
  backTo,
  backLabel,
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
  runRepository,
  aboveEvidence,
  secondaryTab,
  dismissButton,
  dismissDialog,
  showMetadata = true,
  children,
}: InboxDetailFrameViewProps): React.JSX.Element {
  const [activeTab, setActiveTab] = useState("overview");
  const hasSource = hasKnownSourceProduct(report.source_products);
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
      {evidenceCount > 0 && (
        <>
          <InboxMetaText className="tabular-nums">
            {evidenceCount} signal{evidenceCount === 1 ? "" : "s"}
          </InboxMetaText>
          <InboxMetaSeparator />
        </>
      )}
      <RelativeTimestamp
        timestamp={report.updated_at ?? report.created_at}
        className="text-[13px]"
      />
      {hasSource && (
        <>
          <InboxMetaSeparator />
          <InboxMetaSourceStack
            sourceProducts={report.source_products}
            labelPrefix="Agent · "
          />
        </>
      )}
      {report.priority && (
        <>
          <InboxMetaSeparator />
          <InboxMetaText>{report.priority}</InboxMetaText>
        </>
      )}
      {runRepository && (
        <>
          <InboxMetaSeparator />
          <Tooltip>
            <TooltipTrigger
              render={<InboxMetaText mono className="cursor-help" />}
            >
              {runRepository}
            </TooltipTrigger>
            <TooltipContent side="top">
              Agent runs for this report work in this repository
            </TooltipContent>
          </Tooltip>
        </>
      )}
      {metaSuffix}
    </>
  );

  return (
    <div className="@container flex min-h-full flex-col">
      <div className="mx-auto flex w-full max-w-[calc(160ch+5rem)] flex-wrap items-center justify-between gap-3 px-6 py-4">
        <div className="flex items-center gap-2 text-[13.5px] text-gray-11">
          <DetailBackLink to={backTo} label={backLabel} />
          {breadcrumb}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2.5">
          {primaryAction}
          {dismissButton}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[calc(160ch+5rem)] px-6 pb-5 text-[14px]">
        <div className="flex @5xl:flex-row flex-col @5xl:items-start overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)">
          <aside className="@5xl:order-none order-2 flex @5xl:w-[26rem] w-full min-w-0 @5xl:shrink-0 flex-col gap-5 @5xl:self-stretch border-(--gray-5) border-t @5xl:border-t-0 @5xl:border-r p-5">
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

          <main className="@5xl:order-none order-1 flex min-w-0 flex-1 flex-col @5xl:px-8 px-6 py-5">
            {secondaryTab ? (
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList
                  variant="line"
                  className="mb-5 h-auto w-full justify-start gap-0.5 border-(--gray-5) border-b"
                >
                  <TabsTrigger value="overview" className="gap-1.5 px-2.5 py-2">
                    <span className="font-bold text-[14px]">
                      {summarySection.title}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value="secondary"
                    className="gap-1.5 px-2.5 py-2"
                  >
                    <span className="flex items-center gap-1.5 font-medium text-[14px]">
                      {secondaryTab.label}
                    </span>
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            ) : (
              <div className="mb-5 flex items-center gap-2.5 border-(--gray-5) border-b pb-3">
                <span className="font-bold text-[14px] text-gray-12">
                  {summarySection.title}
                </span>
                <span className="flex-1" />
                <span className="text-[12px] text-gray-10">
                  Generated <RelativeTimestamp timestamp={report.created_at} />
                </span>
              </div>
            )}

            {secondaryTab && activeTab === "secondary" ? (
              <div className="flex min-w-0 flex-col gap-5">
                <h1 className="m-0 min-w-0 font-bold text-[24px] text-gray-12 leading-tight tracking-tight">
                  {title}
                </h1>
                {secondaryTab.content}
              </div>
            ) : (
              <div className="flex min-h-full min-w-0 flex-col gap-6">
                <div className="flex flex-col gap-2">
                  <h1 className="m-0 min-w-0 font-bold text-[24px] text-gray-12 leading-tight tracking-tight">
                    {title}
                  </h1>
                  {showMetadata && (
                    <div className="flex flex-wrap items-center gap-2">
                      {report.status !== "ready" && (
                        <SignalReportStatusBadge status={report.status} />
                      )}
                      {report.is_suggested_reviewer && <ForYouBadge />}
                      <InboxMetaRow>{reportMeta}</InboxMetaRow>
                    </div>
                  )}
                </div>
                {aboveSummary}
                <ReportSummaryDocument report={report} />
                {belowSummary}
                {footer && <div className="mt-auto">{footer}</div>}
              </div>
            )}
          </main>
        </div>
        {dismissDialog}
      </div>
    </div>
  );
}
