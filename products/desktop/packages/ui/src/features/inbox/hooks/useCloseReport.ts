import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { navigateToReportSource } from "@posthog/ui/router/navigationBridge";
import {
  resolveNavigationSource,
  useReportSourceHref,
} from "@posthog/ui/router/reportNavigation";
import { useEffect, useMemo, useRef } from "react";

/**
 * Puts the report down and leaves its list standing, the way Activity closes an
 * item. Null when the report names no source, because then no list sits beside
 * it to close back to.
 */
export function useCloseReport(): (() => void) | null {
  const href = resolveNavigationSource(useReportSourceHref())?.href;
  const triageOrigin = useInboxTriageOrigin();
  return useMemo(
    () =>
      href
        ? () => navigateToReportSource(href, triageOrigin?.reportId ?? null)
        : null,
    [href, triageOrigin],
  );
}

/**
 * A report that ends while it is open closes itself, so the list comes back
 * instead of a terminal report with its actions gone. Only the transition into
 * a terminal status closes, because a report opened out of the Archive is
 * already terminal and its read-only detail is the destination.
 */
export function useCloseReportWhenTerminal(report: SignalReport): void {
  const closeReport = useCloseReport();
  const terminal = isDismissedReport(report);
  // The page swaps reports without remounting, so the id says whose transition this is.
  const activeReportId = useRef<string | null>(null);

  useEffect(() => {
    if (!terminal) {
      activeReportId.current = report.id;
      return;
    }
    if (activeReportId.current !== report.id || !closeReport) return;
    activeReportId.current = null;
    closeReport();
  }, [closeReport, report.id, terminal]);
}
