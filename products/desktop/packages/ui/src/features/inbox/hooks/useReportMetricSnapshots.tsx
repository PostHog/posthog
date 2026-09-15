import { MAX_REPORT_METRIC_REFRESH_REPORTS } from "@posthog/api-client/posthog-client";
import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { mergeReportMetricSnapshots } from "@posthog/core/inbox/reportMetrics";
import type { SignalReport, SignalReportMetric } from "@posthog/shared/types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { createContext, type ReactNode, useContext, useMemo } from "react";

type MetricSnapshots = Record<string, SignalReportMetric[]>;

const EMPTY_SNAPSHOTS: MetricSnapshots = {};

const ReportMetricSnapshotsContext =
  createContext<MetricSnapshots>(EMPTY_SNAPSHOTS);

/** Reports whose metrics the backend will re-measure; the rest keep their saved snapshot. */
function refreshableReportIds(reports: readonly SignalReport[]): string[] {
  return reports
    .filter(
      (report) =>
        (report.status === "ready" || report.status === "pending_input") &&
        (report.metrics?.length ?? 0) > 0,
    )
    .map((report) => report.id)
    .slice(0, MAX_REPORT_METRIC_REFRESH_REPORTS);
}

/**
 * Re-measures the metrics of the reports on screen in one bounded call, so a
 * row shows what its metric reads now rather than when the report was written.
 * The snapshots are shared through context instead of written back into the
 * report caches: a refresh replaces numbers only, and the report itself must
 * keep whatever the list response said.
 *
 * A failed refresh resolves to nothing, which leaves every row on its saved
 * snapshot. The window matches the backend's own snapshot freshness, so
 * revisiting the inbox does not re-run every row's query.
 */
export function ReportMetricSnapshotsProvider({
  reports,
  children,
}: {
  reports: readonly SignalReport[];
  children: ReactNode;
}): React.JSX.Element {
  const reportIds = useMemo(() => refreshableReportIds(reports), [reports]);
  const query = useAuthenticatedQuery<MetricSnapshots>(
    inboxReportKeys.metricSnapshots(reportIds),
    (client) => client.refreshSignalReportMetrics(reportIds),
    {
      enabled: reportIds.length > 0,
      staleTime: 15 * 60_000,
      refetchOnWindowFocus: false,
      retry: false,
    },
  );

  return (
    <ReportMetricSnapshotsContext.Provider
      value={query.data ?? EMPTY_SNAPSHOTS}
    >
      {children}
    </ReportMetricSnapshotsContext.Provider>
  );
}

/** A report's metrics with any fresher snapshot from the surrounding list merged in. */
export function useRefreshedReportMetrics(
  report: SignalReport,
): SignalReportMetric[] {
  const snapshots = useContext(ReportMetricSnapshotsContext);
  const refreshed = snapshots[report.id];
  return useMemo(
    () => mergeReportMetricSnapshots(report.metrics, refreshed),
    [report.metrics, refreshed],
  );
}
