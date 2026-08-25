import {
  ChartLineUpIcon,
  type IconProps,
  LightbulbIcon,
  TargetIcon,
  WarningCircleIcon,
  WrenchIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import { splitReportSummary } from "@posthog/core/inbox/reportPresentation";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { InboxDetailPageHeader } from "@posthog/ui/features/inbox/components/InboxDetailPageHeader";
import {
  InboxMetaSeparator,
  InboxMetaText,
} from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { ReportReviewersHeader } from "@posthog/ui/features/inbox/components/ReportReviewersHeader";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import {
  SignalsList,
  SignalsListSkeleton,
} from "@posthog/ui/features/inbox/components/SignalsList";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import type { InboxListRoute } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import {
  useInboxReportArtefacts,
  useInboxReportSignals,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { type ComponentType, type ReactNode, useMemo, useState } from "react";

interface InboxDetailFrameProps {
  report: SignalReport;
  /** List route for the back-link (e.g. "/inbox/pulls"). */
  backTo: InboxListRoute | (string & {});
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
  /** Variant-specific primary action button (e.g. "Open PR in GitHub" or "Copy link"). */
  primaryAction?: ReactNode;
  /** Rendered at the top of the main column, before the summary (the verdict banner). */
  aboveSummary?: ReactNode;
  /** Summary section: icon + title (e.g. "Summary" / "What the agent looked at"). */
  summarySection: {
    Icon: ComponentType<IconProps>;
    title: string;
  };
  /** Sections rendered in the main column under the summary (e.g. PR comments). */
  belowSummary?: ReactNode;
  /** Content that closes the overview after both responsive columns. */
  footer?: ReactNode;
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
  aboveSummary,
  summarySection,
  belowSummary,
  footer,
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
  // The repo the report's own selection step chose — the one a Discuss, Canvas,
  // or PR run will work in (the server resolves runs from this same artefact).
  // Null covers both "no selection yet" and a deliberate no-repo choice; the
  // byline stays quiet for those. The decision section already fetches these
  // artefacts, so this query is warm.
  const { data: artefactsResp } = useInboxReportArtefacts(report.id);
  const runRepository = extractRepoSelectionRepository(artefactsResp?.results);
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
            {/* Ready is the default state and the decision block says so; only
                an exceptional status (failed, running, archived) earns a badge. */}
            {report.status !== "ready" && (
              <SignalReportStatusBadge status={report.status} />
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
        }
        actions={
          <div className="flex items-center gap-2.5">
            <ReportReviewersHeader report={report} />
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
                <span className="font-medium text-[14px]">Overview</span>
              </TabsTrigger>
              <TabsTrigger value="secondary" className="gap-1.5 px-2.5 py-2">
                <span className="flex items-center gap-1.5 font-medium text-[14px]">
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
             we set the same 14px font context that the prose uses so `ch` here
             resolves to the same width as inside the markdown.
           - Right column grows beyond the prose to use the leftover space, but
             the grid container is capped so the right column never exceeds 50%
             of total width. Wider viewports just get larger side gutters.
        */}
      <div className="@container mx-auto w-full max-w-[calc(160ch+5rem)] px-6 py-5 text-[14px]">
        {secondaryTab && activeTab === "secondary" ? (
          <div className="flex min-w-0 flex-col gap-5">
            {secondaryTab.content}
          </div>
        ) : (
          <div className="grid @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] grid-cols-1 gap-5">
            <div className="flex min-w-0 flex-col gap-5">
              {aboveSummary}
              <ReportSummarySlots
                report={report}
                fallbackTitle={summarySection.title}
                Icon={SummaryIcon}
              />
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
                    <span className="cursor-default select-none text-[12px] text-gray-10 tabular-nums">
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
        {(!secondaryTab || activeTab === "overview") && footer && (
          <div className="mt-5">{footer}</div>
        )}
        {showDismiss && dismissDialog}
      </div>
    </div>
  );
}

/**
 * The summary rendered as labeled slots instead of one wall of prose: the
 * lede (the summary's own tl;dr) stays above the fold, the first section
 * opens by default, and the rest sit behind disclosure. Nothing is cut —
 * the reader jumps to the slot they need instead of reading linearly.
 * Heading-less summaries render whole, exactly as before.
 */
function ReportSummarySlots({
  report,
  fallbackTitle,
  Icon,
}: {
  report: SignalReport;
  fallbackTitle: string;
  Icon: ComponentType<IconProps>;
}) {
  const split = useMemo(
    () => splitReportSummary(report.summary),
    [report.summary],
  );
  const chartIds = renderableReportChartIds(report.charts);
  const charts = report.charts && report.charts.length > 0 && (
    <div className="mt-4">
      <ReportChartsSection reportId={report.id} charts={report.charts} />
    </div>
  );

  const sectionIcon = (title: string): ComponentType<IconProps> => {
    const normalizedTitle = title.toLowerCase();
    if (normalizedTitle.includes("problem")) return WarningCircleIcon;
    if (normalizedTitle.includes("impact")) return ChartLineUpIcon;
    if (
      normalizedTitle.includes("solution") ||
      normalizedTitle.includes("recommend")
    ) {
      return LightbulbIcon;
    }
    if (
      normalizedTitle.includes("implementation") ||
      normalizedTitle.includes("fix")
    ) {
      return WrenchIcon;
    }
    return TargetIcon;
  };

  if (split.sections.length === 0) {
    return (
      <DetailSection Icon={Icon} title={fallbackTitle} collapsible>
        <SignalReportSummaryMarkdown
          content={report.summary}
          fallback="No summary yet. The agent is still investigating."
          variant="detail"
          pending={report.status === "in_progress"}
          chartIds={chartIds}
        />
        {charts}
      </DetailSection>
    );
  }

  return (
    <>
      {split.lede && (
        <DetailSection Icon={Icon} title={fallbackTitle}>
          <SignalReportSummaryMarkdown
            content={split.lede}
            fallback=""
            variant="detail"
            pending={report.status === "in_progress"}
            chartIds={chartIds}
          />
        </DetailSection>
      )}
      {split.sections.map((section, index) => (
        <DetailSection
          key={`${section.title}-${index}`}
          Icon={sectionIcon(section.title)}
          title={section.title}
          collapsible
          defaultCollapsed={index > 0}
        >
          <SignalReportSummaryMarkdown
            content={section.body}
            fallback=""
            variant="detail"
            pending={false}
            chartIds={chartIds}
          />
        </DetailSection>
      ))}
      {/* Charts stay outside the collapsibles: in-prose chart links jump to
          these anchors, and a jump into a folded section lands nowhere. */}
      {report.charts && report.charts.length > 0 && (
        <DetailSection Icon={ChartLineUpIcon} title="Charts">
          <ReportChartsSection reportId={report.id} charts={report.charts} />
        </DetailSection>
      )}
    </>
  );
}
