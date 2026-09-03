import {
  ArrowDownIcon,
  ArrowsOutSimpleIcon,
  ArrowUpIcon,
  ChartLineUpIcon,
  FileTextIcon,
  XIcon,
} from "@phosphor-icons/react";
import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  parseConventionalCommitTitle,
  splitReportSummary,
} from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { KeyHint } from "@posthog/ui/primitives/KeyHint";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { ReactNode } from "react";

export interface ReportTriageFocusViewProps {
  report: SignalReport;
  position: number;
  total: number;
  scopeLabel: string;
  hasActiveFilters: boolean;
  previousReport?: SignalReport | null;
  nextReport?: SignalReport | null;
  expanded: boolean;
  prShortcut: "open" | "create" | null;
  /** Shows the X hint: pressing it removes the current user from reviewers. */
  canRemoveSelfFromReviewers: boolean;
  actions: ReactNode;
  reviewers?: ReactNode;
  onExit: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onOpenReport: () => void;
  onToggleSummary: () => void;
}

export function ReportTriageFocusView({
  report,
  position,
  total,
  scopeLabel,
  hasActiveFilters,
  previousReport,
  nextReport,
  expanded,
  prShortcut,
  canRemoveSelfFromReviewers,
  actions,
  reviewers,
  onExit,
  onPrevious,
  onNext,
  onOpenReport,
  onToggleSummary,
}: ReportTriageFocusViewProps): React.JSX.Element {
  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const reportTitle = displayConventionalCommitTitle(
    report.title,
    "Untitled report",
  );
  const headline = deriveHeadline(report.summary);
  const sourceMeta = (report.source_products ?? [])
    .map((sourceProduct) => getSourceProductMeta(sourceProduct))
    .find((item) => item !== null);
  const SourceIcon = sourceMeta?.Icon;
  const summarySplit = splitReportSummary(report.summary);
  const chartIds = renderableReportChartIds(report.charts);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col justify-center gap-3 px-6 py-6">
      <div className="flex items-center justify-between gap-3 px-1">
        <span className="text-[13px] text-gray-10 tabular-nums">
          {position} of {total} · {scopeLabel}
          {hasActiveFilters ? " · Filtered" : ""}
        </span>
        <Button type="button" variant="link-muted" size="sm" onClick={onExit}>
          <XIcon />
          Exit triage
        </Button>
      </div>

      {previousReport && (
        <Button
          type="button"
          variant="outline"
          className="h-12 w-full justify-start gap-3 px-4 text-gray-9"
          onClick={onPrevious}
        >
          <ArrowUpIcon />
          <span className="truncate">
            {displayConventionalCommitTitle(
              previousReport.title,
              "Untitled report",
            )}
          </span>
        </Button>
      )}

      <section className="overflow-hidden rounded-lg border border-border bg-(--color-panel-solid)">
        <div className="flex flex-col gap-4 p-5">
          {sourceMeta && SourceIcon && (
            <div className="flex items-center gap-2 font-medium text-[13px] text-gray-10">
              <SourceIcon style={{ color: sourceMeta.color }} />
              <span>{sourceMeta.label}</span>
            </div>
          )}

          <div className="flex items-center gap-4">
            <PriorityMonogram priority={report.priority} size="large" />
            <h2 className="min-w-0 font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
              {conventionalTitle && (
                <ConventionalCommitScopeTag
                  type={conventionalTitle.type}
                  scope={conventionalTitle.scope}
                />
              )}
              {reportTitle}
            </h2>
          </div>

          {headline && (
            <p className="text-[14px] text-gray-11 leading-relaxed">
              {headline}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 text-[13px] text-gray-10">
            <span className="tabular-nums">
              {report.signal_count} signal
              {report.signal_count === 1 ? "" : "s"}
            </span>
            <span aria-hidden>·</span>
            <span className="flex items-center gap-1">
              First seen
              <RelativeTimestamp
                timestamp={report.created_at}
                className="text-[13px]"
              />
            </span>
            <span aria-hidden>·</span>
            <span className="flex items-center gap-1">
              Last updated
              <RelativeTimestamp
                timestamp={report.updated_at ?? report.created_at}
                className="text-[13px]"
              />
            </span>
            {reviewers}
          </div>

          {expanded && (
            <div className="flex flex-col gap-3 border-(--gray-5) border-t pt-5">
              {report.charts && report.charts.length > 0 && (
                <DetailSection Icon={ChartLineUpIcon} title="Charts">
                  <ReportChartsSection
                    reportId={report.id}
                    charts={report.charts}
                  />
                </DetailSection>
              )}
              {summarySplit.sections.length === 0 ? (
                <SignalReportSummaryMarkdown
                  content={report.summary}
                  fallback="No summary yet. The agent is still investigating."
                  variant="detail"
                  pending={report.status === "in_progress"}
                  chartIds={chartIds}
                />
              ) : (
                <>
                  {summarySplit.lede && (
                    <SignalReportSummaryMarkdown
                      content={summarySplit.lede}
                      fallback=""
                      variant="detail"
                      pending={report.status === "in_progress"}
                      chartIds={chartIds}
                    />
                  )}
                  {summarySplit.sections.map((section, sectionIndex) => (
                    <DetailSection
                      key={`${report.id}-${section.title}-${sectionIndex}`}
                      Icon={FileTextIcon}
                      title={section.title}
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
                </>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-(--gray-5) border-t bg-(--gray-2) px-5 py-3">
          {actions}
          <div className="ml-auto flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-9 gap-2 px-4 text-[14px]"
              onClick={onOpenReport}
            >
              <ArrowsOutSimpleIcon />
              Open report
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-9 gap-2 px-4 text-[14px]"
              onClick={onToggleSummary}
            >
              <FileTextIcon />
              {expanded ? "Hide summary" : "Read summary"}
            </Button>
          </div>
        </div>
      </section>

      {nextReport && (
        <Button
          type="button"
          variant="outline"
          className="h-12 w-full justify-start gap-3 px-4 text-gray-9"
          onClick={onNext}
        >
          <ArrowDownIcon />
          <span className="truncate">
            {displayConventionalCommitTitle(
              nextReport.title,
              "Untitled report",
            )}
          </span>
        </Button>
      )}

      <div className="flex flex-wrap items-center justify-center gap-4 text-[13px] text-gray-10">
        <span className="flex items-center gap-1">
          <KeyHint>↑</KeyHint>
          <KeyHint>↓</KeyHint>
          move
        </span>
        {prShortcut && (
          <span className="flex items-center gap-1">
            <KeyHint>C</KeyHint>
            {prShortcut === "open" ? "open PR" : "create PR"}
          </span>
        )}
        <span className="flex items-center gap-1">
          <KeyHint>R</KeyHint>
          resolve
        </span>
        <span className="flex items-center gap-1">
          <KeyHint>A</KeyHint>
          dismiss
        </span>
        <span className="flex items-center gap-1">
          <KeyHint>O</KeyHint>
          open
        </span>
        {canRemoveSelfFromReviewers && (
          <span className="flex items-center gap-1">
            <KeyHint>X</KeyHint>
            remove me as reviewer
          </span>
        )}
        <span className="flex items-center gap-1">
          <KeyHint>Enter</KeyHint>
          summary
        </span>
        <span className="flex items-center gap-1">
          <KeyHint>Esc</KeyHint>
          exit
        </span>
      </div>
    </div>
  );
}
