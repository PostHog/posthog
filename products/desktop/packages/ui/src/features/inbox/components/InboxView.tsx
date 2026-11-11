import { EnvelopeSimpleIcon } from "@phosphor-icons/react";
import { isInboxDetailPath } from "@posthog/core/inbox/reportMembership";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { InboxHomePane } from "@posthog/ui/features/inbox/components/InboxHomePane";
import { InboxTriagePane } from "@posthog/ui/features/inbox/components/InboxTriagePane";
import { ReportsInboxView } from "@posthog/ui/features/inbox/components/ReportsInboxView";
import { resetReportOpenTrackerHistory } from "@posthog/ui/features/inbox/hooks/useReportOpenTracker";
import { isInboxTriagePath } from "@posthog/ui/features/inbox/triageRoute";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo } from "react";

/**
 * Inbox shell. Owns the in-page header (title + RFC subtitle + tab bar) and
 * the global-header chrome lockup. Tab bodies render via `<Outlet />` so each
 * sub-route renders the matching tab content full-width below the header.
 */
export function InboxView() {
  const headerContent = useMemo(
    () => (
      <div className="flex w-full min-w-0 items-center gap-2">
        <EnvelopeSimpleIcon size={12} className="shrink-0 text-gray-10" />
        <span
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Self-driving"
        >
          Self-driving
        </span>
      </div>
    ),
    [],
  );

  // Scope report-to-report navigation history to this inbox visit so the first
  // report opened after (re)entering the inbox has no stale previous_report_id.
  useEffect(() => {
    resetReportOpenTrackerHistory();
  }, []);

  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isDetailView = isInboxDetailPath(pathname);

  const spacesLayout = useChannelsLayout();
  // Beside the rail's list the pane names nothing the column has not said.
  const paneOwnsTitle = spacesLayout && !isDetailView;
  useSetHeaderContent(paneOwnsTitle ? null : headerContent);

  // The reports inbox is one sectioned, keyboard-triageable page. Detail
  // routes keep their own bodies.
  if (!isDetailView) {
    if (isInboxTriagePath(pathname)) return <InboxTriagePane />;
    // The view owns its height so its page header stays pinned while the
    // sections scroll — the same shape ActivityView has.
    return spacesLayout ? <InboxHomePane /> : <ReportsInboxView />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  );
}
