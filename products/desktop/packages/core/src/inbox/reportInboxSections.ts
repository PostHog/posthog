import type { SignalReport } from "@posthog/shared/types";

/**
 * The global reports inbox shows every live report in two sections. The
 * boundary is deliberately a server-countable dimension — report status —
 * because the section headers and nav badges are server-side count queries,
 * and a boundary the API can't filter on (actionability, PR-merged state)
 * produces headline numbers no query can verify.
 */
export interface InboxReportSections {
  /** Ready: research done, a person decides — act, review the PR, or archive. */
  decision: SignalReport[];
  /** Still moving or stuck: running, queued, waiting on input, failed. */
  monitoring: SignalReport[];
}

/**
 * Whether a report is in the "Needs a decision" section: exactly the `ready`
 * status. Archiving an FYI is a decision too, so ready-but-not-actionable
 * reports stay here (a row-level hint conveys that) rather than defining a
 * section boundary counts can't reproduce.
 */
export function reportNeedsDecision(report: SignalReport): boolean {
  return report.status === "ready";
}

/**
 * Partition the loaded list into the two sections, preserving its order. The
 * list arrives sorted by the user's own sort (applied server-side by the
 * filter bar); section totals come from server count queries, not from this
 * partition — these arrays only feed the rendered rows.
 */
export function partitionInboxReports(
  reports: SignalReport[],
): InboxReportSections {
  const decision: SignalReport[] = [];
  const monitoring: SignalReport[] = [];
  for (const report of reports) {
    (reportNeedsDecision(report) ? decision : monitoring).push(report);
  }
  return { decision, monitoring };
}
