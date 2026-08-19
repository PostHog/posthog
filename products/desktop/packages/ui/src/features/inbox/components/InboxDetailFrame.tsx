import type { IconProps } from "@phosphor-icons/react";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import { isStatusRedundantWithActionability } from "@posthog/core/inbox/reportPresentation";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { InboxDetailPageHeader } from "@posthog/ui/features/inbox/components/InboxDetailPageHeader";
import {
  InboxMetaSeparator,
  InboxMetaText,
} from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import {
  SignalsList,
  SignalsListSkeleton,
} from "@posthog/ui/features/inbox/components/SignalsList";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import type { InboxListRoute } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportSignals } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { type ComponentType, type ReactNode, useState } from "react";

interface InboxDetailFrameProps {
  report: SignalReport;
  /** List route for the back-link (e.g. "/code/inbox/pulls"). */
  backTo: InboxListRoute;
  backLabel: string;
  /**
   * Whether to render the Dismiss button + dialog. Off for already-dismissed
   * reports (the Dismissed tab), where dismissing again makes no sense.
   */
  showDismiss?: boolean;
  /** Title fallback when `report.title` is blank. */
  fallbackTitle: string;
  /** Optional breadcrumb fragment (e.g. PR repo slug + number). */
  breadcrumb?: ReactNode;
  /** Meta items rendered before the signals count + timestamp. */
  metaPrefix?: ReactNode;
  /** Meta items appended after the timestamp + source (e.g. PR diff stats). */
  metaSuffix?: ReactNode;
  /** Variant-specific primary action button (e.g. "Open in GitHub" or "Copy link"). */
  primaryAction?: ReactNode;
  /** Summary section: icon + title (e.g. "Summary" / "What the agent looked at"). */
  summarySection: {
    Icon: ComponentType<IconProps>;
    title: string;
  };
  /** Sections rendered in the main column under the summary (e.g. PR comments). */
  belowSummary?: ReactNode;
  /** Optional "Evidence" section icon + title; null hides it. */
  evidenceSection: {
    Icon: ComponentType<IconProps>;
    title: string;
  } | null;
  /** Right-column cards rendered above the Evidence card (checks, reviewers). */
  aboveEvidence?: ReactNode;
  /**
   * Second tab beside Overview (the web detail's "Files changed"). Its content
   * replaces the whole overview grid while selected.
   */
  secondaryTab?: { label: ReactNode; content: ReactNode };
  /** Sections rendered alongside the summary (Tasks, Activity, …). */
  children?: ReactNode;
}

/**
 * Shared chrome for inbox detail screens. The body lays out the report
 * summary on the left and supporting sections (Evidence, Tasks, Suggested
 * reviewers) on the right when the container is wide enough; everything
 * stacks into a single column below the breakpoint. AgentRunDetail keeps
 * its own layout – its sections (Run summary, Task log) diverge enough that
 * sharing this frame would obscure intent.
 */
export function InboxDetailFrame({
  report,
  backTo,
  backLabel,
  fallbackTitle,
  breadcrumb,
  metaPrefix,
  metaSuffix,
  primaryAction,
  summarySection,
  belowSummary,
  evidenceSection,
  aboveEvidence,
  secondaryTab,
  showDismiss = true,
  children,
}: InboxDetailFrameProps) {
  const [activeTab, setActiveTab] = useState("overview");
  const { data: signalsResp } = useInboxReportSignals(report.id);
  const signals = signalsResp?.signals ?? [];
  const signalsLoaded = signalsResp !== undefined;
  const hasSource = hasKnownSourceProduct(report.source_products);
  const { actionButton: dismissButton, dialog: dismissDialog } =
    useInboxReportDismissAction(report);

  const SummaryIcon = summarySection.Icon;
  const EvidenceIcon = evidenceSection?.Icon;
  // While the signals query is in flight we already know how many findings to
  // expect – use `report.signal_count` so the meta row and Evidence skeleton
  // render immediately. Once the actual signals load, switch to the live count.
  const evidenceCount = signalsLoaded ? signals.length : report.signal_count;
  const hasEvidence =
    evidenceSection != null && EvidenceIcon != null && evidenceCount > 0;

  return (
    <div className="flex min-h-full flex-col">
      <InboxDetailPageHeader
        backTo={backTo}
        backLabel={backLabel}
        breadcrumb={breadcrumb}
        reportTitle={report.title}
        fallbackTitle={fallbackTitle}
        badges={
          <>
            {report.priority && (
              <SignalReportPriorityBadge priority={report.priority} />
            )}
            {/*
              When the report has been classified by the Responder, the
              actionability verdict (Actionable / Needs input / Not actionable)
              takes the status badge's slot where the status would only repeat
              it. Other statuses (in-progress, candidate, failed, …) still
              surface as a badge.
             */}
            {!isStatusRedundantWithActionability(
              report.status,
              report.actionability,
            ) && <SignalReportStatusBadge status={report.status} />}
            {report.actionability && (
              <SignalReportActionabilityBadge
                actionability={report.actionability}
              />
            )}
            {report.is_suggested_reviewer && <ForYouBadge />}
          </>
        }
        meta={
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
              className="text-[12px]"
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
            {metaSuffix}
          </>
        }
        actions={
          <div className="flex items-center gap-2.5">
            {primaryAction}
            {showDismiss && dismissButton}
          </div>
        }
      />

      {secondaryTab && (
        <div className="border-(--gray-5) border-b px-6">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList variant="line" className="h-auto gap-0.5">
              <TabsTrigger value="overview" className="gap-1.5 px-2.5 py-2">
                <span className="font-medium text-[13px]">Overview</span>
              </TabsTrigger>
              <TabsTrigger value="secondary" className="gap-1.5 px-2.5 py-2">
                <span className="flex items-center gap-1.5 font-medium text-[13px]">
                  {secondaryTab.label}
                </span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      )}

      {/*
         The detail body is a container-query grid:
           - Left column caps at 80ch – matches the prose width inside, because
             we set the same 13px font context that the prose uses so `ch` here
             resolves to the same width as inside the markdown.
           - Right column grows beyond the prose to use the leftover space, but
             the grid container is capped so the right column never exceeds 50%
             of total width. Wider viewports just get larger side gutters.
        */}
      <div className="@container mx-auto w-full max-w-[calc(160ch+5rem)] px-6 py-5 text-[13px]">
        {secondaryTab && activeTab === "secondary" ? (
          <div className="flex min-w-0 flex-col gap-5">
            {secondaryTab.content}
          </div>
        ) : (
          <div className="grid @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] grid-cols-1 gap-5">
            <div className="flex min-w-0 flex-col gap-5">
              <DetailSection
                Icon={SummaryIcon}
                title={summarySection.title}
                collapsible
              >
                <SignalReportSummaryMarkdown
                  content={report.summary}
                  fallback="No summary yet. The agent is still investigating."
                  variant="detail"
                  pending={report.status === "in_progress"}
                  chartIds={renderableReportChartIds(report.charts)}
                />
                {report.charts && report.charts.length > 0 && (
                  <div className="mt-4">
                    <ReportChartsSection
                      reportId={report.id}
                      charts={report.charts}
                    />
                  </div>
                )}
              </DetailSection>
              {belowSummary}
            </div>

            <div className="flex min-w-0 flex-col gap-5">
              {aboveEvidence}
              {hasEvidence && (
                <RightColumnSection
                  Icon={EvidenceIcon}
                  title={evidenceSection.title}
                  collapsible
                  rightSlot={
                    <span className="cursor-default select-none text-[11px] text-gray-10 tabular-nums">
                      {evidenceCount} signal
                      {evidenceCount === 1 ? "" : "s"}
                    </span>
                  }
                >
                  {signals.length > 0 ? (
                    <SignalsList signals={signals} />
                  ) : (
                    <SignalsListSkeleton count={evidenceCount} />
                  )}
                </RightColumnSection>
              )}
              {children}
            </div>
          </div>
        )}
        {showDismiss && dismissDialog}
      </div>
    </div>
  );
}
