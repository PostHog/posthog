import { renderableReportChartIds } from "@posthog/core/inbox/reportCharts";
import { splitReportSummary } from "@posthog/core/inbox/reportPresentation";
import type { SignalReport } from "@posthog/shared/types";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";

export function ReportSummaryDocument({
  report,
}: {
  report: SignalReport;
}): React.JSX.Element {
  const split = splitReportSummary(report.summary);
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
