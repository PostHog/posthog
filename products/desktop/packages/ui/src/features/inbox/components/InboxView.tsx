import { EnvelopeSimpleIcon } from "@phosphor-icons/react";
import { isInboxDetailPath } from "@posthog/core/inbox/reportMembership";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import { InboxPageHeader } from "@posthog/ui/features/inbox/components/InboxPageHeader";
import { ReportsInboxView } from "@posthog/ui/features/inbox/components/ReportsInboxView";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { resetReportOpenTrackerHistory } from "@posthog/ui/features/inbox/hooks/useReportOpenTracker";
import { useTrackInboxViewed } from "@posthog/ui/features/inbox/hooks/useTrackInboxViewed";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Flex, Text } from "@radix-ui/themes";
import { Navigate, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo } from "react";

/**
 * Inbox shell. Owns the in-page header (title + RFC subtitle + tab bar) and
 * the global-header chrome lockup. Tab bodies render via `<Outlet />` so each
 * sub-route renders the matching tab content full-width below the header.
 */
export function InboxView() {
  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <EnvelopeSimpleIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Self-driving"
        >
          Self-driving
        </Text>
      </Flex>
    ),
    [],
  );

  useSetHeaderContent(headerContent);

  // Scope report-to-report navigation history to this inbox visit so the first
  // report opened after (re)entering the inbox has no stale previous_report_id.
  useEffect(() => {
    resetReportOpenTrackerHistory();
  }, []);

  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isDetailView = isInboxDetailPath(pathname);

  const inboxAvailable = useInboxAvailable();
  // The global reports inbox replaces the pipeline tabs with one sectioned,
  // keyboard-triageable page, and reclaims the inbox slot from the spaces
  // redirect below. Detail routes keep their own bodies.
  const reportsInboxEnabled = useReportsInboxEnabled();
  const listEnabled = !isDetailView && inboxAvailable;
  const legacyListEnabled = listEnabled && !reportsInboxEnabled;
  const { counts } = useInboxAllReports({
    enabled: legacyListEnabled,
    withReportsCount: true,
  });

  useTrackInboxViewed({ enabled: legacyListEnabled });

  if (reportsInboxEnabled && !isDetailView) {
    // The view owns its height so its page header stays pinned while the
    // sections scroll — the same shape ActivityView has.
    return <ReportsInboxView />;
  }

  // With channel reports on, spaces replace the inbox as the home for reports.
  // List tabs reached through stale history or bookmarks land on the spaces
  // index; detail URLs keep working (deep links and old history still carry
  // them, and the in-space route can't be derived from a bare report URL here).
  if (!inboxAvailable && !isDetailView) {
    return <Navigate replace to="/website" />;
  }

  return (
    <Flex direction="column" className="h-full min-h-0">
      {!isDetailView && <InboxPageHeader counts={counts} />}
      <div className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </div>
    </Flex>
  );
}
