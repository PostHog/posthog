import type { IconProps } from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import {
  humanizeReportTitle,
  parseConventionalCommitTitle,
  splitReportSummary,
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
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import {
  InboxMetaRow,
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

  const EvidenceIcon = evidenceSection?.Icon;
  const evidenceUnavailable =
    signalsLoaded && signalsResp?.report === null && report.signal_count > 0;
  // Preserve the report's known count while loading or when the detail request
  // failed. An unavailable response must not make Evidence disappear while a
  // generic activity log remains on screen.
  const evidenceCount =
    !signalsLoaded || evidenceUnavailable
      ? report.signal_count
      : signals.length;
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
        <div className="flex items-center gap-2.5">
          <ReportReviewersHeader report={report} />
          {primaryAction}
          {showDismiss && dismissButton}
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
                    {evidenceCount} signal
                    {evidenceCount === 1 ? "" : "s"}
                  </span>
                }
              >
                {evidenceUnavailable ? (
                  <p className="m-0 text-[13px] text-gray-10">
                    Couldn't load the evidence for this report. Reopen the
                    report to try again.
                  </p>
                ) : signals.length > 0 ? (
                  <SignalsList signals={signals} />
                ) : (
                  <SignalsListSkeleton count={evidenceCount} />
                )}
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
                    <span className="font-medium text-[14px]">
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
                <span className="font-semibold text-[14px] text-gray-12">
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
                  <div className="flex flex-wrap items-center gap-2">
                    {report.status !== "ready" && (
                      <SignalReportStatusBadge status={report.status} />
                    )}
                    {report.is_suggested_reviewer && <ForYouBadge />}
                    <InboxMetaRow>{reportMeta}</InboxMetaRow>
                  </div>
                </div>
                {aboveSummary}
                <ReportSummaryDocument report={report} />
                {belowSummary}
                {footer && <div className="mt-auto">{footer}</div>}
              </div>
            )}
          </main>
        </div>
        {showDismiss && dismissDialog}
      </div>
    </div>
  );
}

function ReportSummaryDocument({ report }: { report: SignalReport }) {
  const split = useMemo(
    () => splitReportSummary(report.summary),
    [report.summary],
  );
  const chartIds = renderableReportChartIds(report.charts);

  if (split.sections.length === 0) {
    return (
      <div className="flex flex-col gap-5">
        <SignalReportSummaryMarkdown
          content={report.summary}
          fallback="No summary yet. The agent is still investigating."
          variant="detail"
          pending={report.status === "in_progress"}
          chartIds={chartIds}
        />
        {report.charts && report.charts.length > 0 && (
          <ReportChartsSection reportId={report.id} charts={report.charts} />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {split.lede && (
        <div className="text-[16px] text-gray-12">
          <SignalReportSummaryMarkdown
            content={split.lede}
            fallback=""
            variant="detail"
            pending={report.status === "in_progress"}
            chartIds={chartIds}
          />
        </div>
      )}
      {report.charts && report.charts.length > 0 && (
        <div className="flex flex-col gap-3">
          <ReportChartsSection reportId={report.id} charts={report.charts} />
        </div>
      )}
      {split.sections.map((section, index) => (
        <section
          key={`${section.title}-${index}`}
          className="flex flex-col gap-2"
        >
          <h2 className="m-0 font-semibold text-[18px] text-gray-12">
            {section.title}
          </h2>
          <SignalReportSummaryMarkdown
            content={section.body}
            fallback=""
            variant="detail"
            pending={false}
            chartIds={chartIds}
          />
        </section>
      ))}
    </div>
  );
}
