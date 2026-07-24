import {
  isDismissedReport,
  isPullRequestReport,
  isReportTabReport,
} from "@posthog/core/inbox/reportMembership";
import { Spinner } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { DetailBackLink } from "@posthog/ui/features/inbox/components/DetailBackLink";
import type { InboxListRoute } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxReportById } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  type InboxDetailTab,
  useReportOpenTracker,
} from "@posthog/ui/features/inbox/hooks/useReportOpenTracker";
import { Flex, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useEffect } from "react";

interface InboxReportDetailGateProps {
  reportId: string;
  cachedReport?: SignalReport | null;
  backTo: InboxListRoute;
  backLabel: string;
  /**
   * Where the missing-report shell's back link points, when it should differ
   * from `backTo`. The Archive detail sets these to the recorded origin so the
   * link follows the user's path in, while `backTo` stays the route identity
   * that drives the status↔route redirect and engagement tracking below.
   * Defaults to `backTo`/`backLabel`.
   */
  backLinkTo?: string;
  backLinkLabel?: string;
  missingCopy: string;
  children: (report: SignalReport) => ReactNode;
}

type InboxDetailRoute =
  | "/code/inbox/pulls/$reportId"
  | "/code/inbox/reports/$reportId"
  | "/code/inbox/runs/$reportId"
  | "/code/inbox/dismissed/$reportId";

/**
 * Detail route a non-suppressed report belongs on, by the same tab-membership
 * predicates the inbox tabs use: Pulls when a PR exists, Reports when it belongs
 * to the Reports tab, otherwise Runs. `isReportTabReport` already excludes
 * `failed` and in-flight runs, so failed/finished and live runs both fall
 * through to Runs — the only tab that actually lists them.
 */
function nonSuppressedDetailRoute(report: SignalReport): InboxDetailRoute {
  if (isPullRequestReport(report)) return "/code/inbox/pulls/$reportId";
  if (isReportTabReport(report)) return "/code/inbox/reports/$reportId";
  return "/code/inbox/runs/$reportId";
}

/**
 * Shared loading + missing-report shell for inbox detail screens. The actual
 * detail body is rendered by the `children` render prop once the report is
 * resolved (either from the fresh query or from the cached/seeded report).
 */
export function InboxReportDetailGate({
  reportId,
  cachedReport = null,
  backTo,
  backLabel,
  backLinkTo,
  backLinkLabel,
  missingCopy,
  children,
}: InboxReportDetailGateProps) {
  const navigate = useNavigate();
  const {
    data: report,
    isLoading,
    isFetching,
    isFetchedAfterMount,
  } = useInboxReportById(reportId);
  const resolvedReport = report ?? cachedReport;

  // Keep the report on the route that matches its status. A status↔route mismatch
  // happens when a URL goes stale — browser history, a bookmark, a copied deep
  // link, or a status change in another session. An archived report (suppressed or
  // resolved) reached via a /pulls, /reports, or /runs URL would otherwise render
  // that tab's full triage actions (archive, discuss, create PR) on an
  // out-of-pipeline report; a restored report reached via /dismissed would offer
  // Restore and silently re-queue it (READY/RESOLVED → POTENTIAL is an allowed
  // server-side transition). Redirect across that dismissed↔pipeline boundary,
  // gated on a settled fetch so we act on the confirmed status rather than a
  // pre-change cache snapshot (the detail query forces a fresh fetch on mount via
  // `initialDataUpdatedAt: 0`). Both terminal states belong on the Archive route,
  // so resolved cards keep their reference-only detail view instead of being
  // bounced to Runs.
  const onDismissedRoute = backTo === "/code/inbox/dismissed";
  const isArchived =
    resolvedReport != null && isDismissedReport(resolvedReport);
  let redirectTo: InboxDetailRoute | null = null;
  if (resolvedReport && !isFetching) {
    if (isArchived && !onDismissedRoute) {
      redirectTo = "/code/inbox/dismissed/$reportId";
    } else if (!isArchived && onDismissedRoute) {
      redirectTo = nonSuppressedDetailRoute(resolvedReport);
    }
  }

  // The redirect above only fires once the fetch settles, so on a triage route we
  // still hold an unconfirmed cached/seeded status during the forced post-mount
  // fetch. Rendering the children then would briefly expose full triage actions
  // (create PR, discuss, archive) for a report that another session has already
  // suppressed, before the redirect kicks in. Hold the spinner until that same
  // fetch settles. The Archive route stays render-from-cache (the PR's instant-open
  // path): it's read-only and its one action, Restore, re-checks status server-side.
  const statusUnconfirmed =
    !onDismissedRoute && isFetching && !isFetchedAfterMount;
  const redirectReportId = resolvedReport?.id;
  useEffect(() => {
    if (!redirectTo || !redirectReportId) return;
    navigate({
      to: redirectTo,
      params: { reportId: redirectReportId },
      replace: true,
      // Carry where we came from into the Archive route so its back link reads
      // "Back to reports/pulls/runs" rather than "Back to archive". This branch
      // only fires from a non-Archive route, so `backTo` is the pipeline origin
      // the user is returning to.
      state:
        redirectTo === "/code/inbox/dismissed/$reportId"
          ? { inboxBackOrigin: { to: backTo, label: backLabel } }
          : undefined,
    });
  }, [redirectTo, redirectReportId, navigate, backTo, backLabel]);

  if ((isLoading && !resolvedReport) || statusUnconfirmed) {
    return (
      <Flex align="center" justify="center" className="py-16">
        <Spinner />
      </Flex>
    );
  }

  if (redirectTo) {
    // Redirecting across the dismissed↔pipeline boundary; render nothing
    // meaningful for the frame we're leaving.
    return (
      <Flex align="center" justify="center" className="py-16">
        <Spinner />
      </Flex>
    );
  }

  if (!resolvedReport) {
    return (
      <Flex direction="column" className="h-full min-h-0">
        <Flex
          direction="column"
          gap="3"
          className="border-(--gray-5) border-b px-6 py-6"
        >
          <DetailBackLink
            to={backLinkTo ?? backTo}
            label={backLinkLabel ?? backLabel}
          />
          <Text className="text-[13px] text-gray-11">{missingCopy}</Text>
        </Flex>
      </Flex>
    );
  }

  const trackTab = tabFromBackTo(backTo);
  return (
    <>
      {trackTab && <ReportOpenTracker report={resolvedReport} tab={trackTab} />}
      {children(resolvedReport)}
    </>
  );
}

/**
 * The Dismissed tab isn't part of the triage funnel and isn't a tracked
 * `InboxDetailTab` (its rank would be measured against the wrong list), so it
 * returns `null` and the open/close engagement events are skipped for it.
 */
function tabFromBackTo(
  backTo: InboxReportDetailGateProps["backTo"],
): InboxDetailTab | null {
  if (backTo === "/code/inbox/pulls") return "pulls";
  if (backTo === "/code/inbox/runs") return "runs";
  if (backTo === "/code/inbox/dismissed") return null;
  return "reports";
}

/**
 * Mounts only once a report is resolved, so the OPENED/CLOSED engagement events
 * bracket the time the detail body is actually on screen. Renders nothing.
 */
function ReportOpenTracker({
  report,
  tab,
}: {
  report: SignalReport;
  tab: InboxDetailTab;
}) {
  useReportOpenTracker(report, tab);
  return null;
}
