import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import {
  resolveNavigationSource,
  useReportSourceHref,
} from "@posthog/ui/router/reportNavigation";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useCallback, useEffect, useRef } from "react";

/**
 * Puts the report down and leaves its list standing, the way Activity closes an
 * item. Null when the report names no source: there is no list beside it and
 * nothing to close back to.
 */
export function useCloseReport(): (() => void) | null {
  const source = resolveNavigationSource(useReportSourceHref());
  // TanStack blanks history state on a plain navigate, so triage's place in
  // the queue has to travel with the navigation or the queue restarts at the top.
  const triageOrigin = useInboxTriageOrigin();
  const href = source?.href;
  const closeReport = useCallback(() => {
    if (!href) return;
    void getRouterOrNull()?.navigate({
      href,
      state: (previous) => ({
        ...previous,
        ...(triageOrigin ? { inboxTriageOrigin: triageOrigin } : {}),
      }),
    });
  }, [href, triageOrigin]);
  return href ? closeReport : null;
}

/**
 * Resolving or archiving a report ends it, so the report closes itself and the
 * list it came from comes back, instead of holding a terminal report on screen
 * with its actions gone. Only the transition closes: a report opened out of the
 * Archive is already terminal, and its read-only detail is where the reader
 * meant to be. Triage keeps its own advance-to-next behavior, since the focus
 * view renders the queue rather than this page.
 */
export function useCloseReportWhenTerminal(report: SignalReport): void {
  const closeReport = useCloseReport();
  const terminal = isDismissedReport(report);
  // The page swaps reports without remounting, so which report was read live is
  // part of what decides whether this is a transition.
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
