import {
  needsImplementationDecision,
  type ReportImplementationState,
} from "@posthog/core/inbox/reportImplementation";
import type { SignalReport } from "@posthog/shared/domain-types";

export function filterReportsForTriage(
  reports: SignalReport[],
  decidedIds: string[],
  implementationStates: ReadonlyMap<string, ReportImplementationState | null>,
): SignalReport[] {
  const decided = new Set(decidedIds);
  return reports.filter(
    (report) =>
      !decided.has(report.id) &&
      needsImplementationDecision(implementationStates.get(report.id) ?? null),
  );
}
