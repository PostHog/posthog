import { resolveInboxReportForRender } from "@posthog/core/inbox/inboxQuery";
import {
  isDismissedReport,
  isPullRequestReport,
  isReportTabReport,
} from "@posthog/core/inbox/reportMembership";
import { Text } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { DetailBackLink } from "@posthog/ui/features/inbox/components/DetailBackLink";
import { InboxReportStatusConfirmedContext } from "@posthog/ui/features/inbox/context/inboxReportStatusContext";
import {
  asInboxBackTarget,
  type InboxListRoute,
  useInboxTriageOrigin,
} from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxReportById } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  type InboxDetailTab,
  useReportOpenTracker,
} from "@posthog/ui/features/inbox/hooks/useReportOpenTracker";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useEffect } from "react";

interface InboxReportDetailGateProps {
  reportId: string;
  cachedReport?: SignalReport | null;
  /** An inbox list route, or any literal path (the in-space detail view). */
  backTo: InboxListRoute | (string & {});
  backLabel: string;
  /**
   * Off for the in-space detail route, which hosts every report status on one
   * URL and so never needs the inbox's status↔route redirect.
   */
  statusRedirect?: boolean;
  requireFreshStatus?: boolean;
  /**
   * Where the missing-report shell's back link points, when it should differ
   * from `backTo`. The Archive detail sets these to the recorded origin so the
   * link follows the user's path in, while `backTo` stays the route identity
   * that drives the status↔route redirect and engagement tracking below.
   * Defaults to `backTo`/`backLabel`.
   */
  backLinkTo?: string;
  backLinkLabel?: string;
  /**
   * Which inbox tab's list the open/close engagement events measure against.
   * Defaults to the tab derived from `backTo`; `null` skips tracking (the
   * Archive tab: its rank would be measured against the wrong list).
   */
  trackTab?: InboxDetailTab | null;
  missingCopy: string;
  children: (report: SignalReport) => ReactNode;
}

type InboxDetailRoute =
  | "/inbox/pulls/$reportId"
  | "/inbox/reports/$reportId"
  | "/inbox/runs/$reportId"
  | "/inbox/dismissed/$reportId";

/**
 * Detail route a non-suppressed report belongs on, by the same tab-membership
 * predicates the inbox tabs use: Pulls when a PR exists, Reports when it belongs
 * to the Reports tab, otherwise Runs. `isReportTabReport` already excludes
 * `failed` and in-flight runs, so failed/finished and live runs both fall
 * through to Runs — the only tab that actually lists them.
 */
function nonSuppressedDetailRoute(report: SignalReport): InboxDetailRoute {
  if (isPullRequestReport(report)) return "/inbox/pulls/$reportId";
  if (isReportTabReport(report)) return "/inbox/reports/$reportId";
  return "/inbox/runs/$reportId";
}

/**
 * Shared loading + missing-report shell for inbox detail screens. The actual
 * detail body is rendered by the `children` render prop once the report is
 * resolved (either from the fresh query or from the cached/seeded report), so a
 * report the reader arrives with in cache paints at once and stays put while
 * the query refreshes behind it.
 */
export function InboxReportDetailGate({
  reportId,
  cachedReport = null,
  backTo,
  backLabel,
  statusRedirect = true,
  requireFreshStatus = false,
  backLinkTo,
  backLinkLabel,
  trackTab = tabFromBackTo(backTo),
  missingCopy,
  children,
}: InboxReportDetailGateProps) {
  const navigate = useNavigate();
  const triageOrigin = useInboxTriageOrigin();
  const {
    data: report,
    isLoading,
    isFetching,
    isFetchedAfterMount,
  } = useInboxReportById(reportId);
  const resolvedReport = resolveInboxReportForRender(report, cachedReport);

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
  const onDismissedRoute = backTo === "/inbox/dismissed";
  const isArchived =
    resolvedReport != null && isDismissedReport(resolvedReport);
  let redirectTo: InboxDetailRoute | null = null;
  if (statusRedirect && resolvedReport && !isFetching) {
    if (isArchived && !onDismissedRoute) {
      redirectTo = "/inbox/dismissed/$reportId";
    } else if (!isArchived && onDismissedRoute) {
      redirectTo = nonSuppressedDetailRoute(resolvedReport);
    }
  }

  // The redirect above only fires once the fetch settles, so on a triage route we
  // still hold an unconfirmed cached/seeded status during the forced post-mount
  // fetch. Exposing full triage actions (create PR, discuss, archive) then would
  // act on a report that another session has already suppressed, before the
  // redirect kicks in. So the actions wait for that fetch, while the report
  // itself stays readable. Blanking the whole frame instead put a spinner over a
  // report the reader was already looking at, and it remounted the children,
  // which counted one open twice. `requireFreshStatus` opts the canonical detail
  // route (which carries no status↔route redirect) into the same wait. The
  // Archive route renders from cache and can't expose actions for the wrong
  // status route.
  const statusConfirmed = !(
    (requireFreshStatus || (statusRedirect && !onDismissedRoute)) &&
    isFetching &&
    !isFetchedAfterMount
  );
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
      // the user is returning to. Validated because `backTo` may be a literal
      // path on the in-space route (which never redirects, but types can't see
      // that).
      state: (previous) => ({
        ...previous,
        ...(redirectTo === "/inbox/dismissed/$reportId"
          ? {
              inboxBackOrigin:
                asInboxBackTarget({ to: backTo, label: backLabel }) ??
                undefined,
            }
          : {}),
        ...(triageOrigin ? { inboxTriageOrigin: triageOrigin } : {}),
      }),
    });
  }, [redirectTo, redirectReportId, navigate, backTo, backLabel, triageOrigin]);

  if (isLoading && !resolvedReport) {
    return <LoadingState className="py-16" />;
  }

  if (redirectTo) {
    // Redirecting across the dismissed↔pipeline boundary; render nothing
    // meaningful for the frame we're leaving.
    return <LoadingState className="py-16" />;
  }

  if (!resolvedReport) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex flex-col gap-3 border-(--gray-5) border-b px-6 py-6">
          <DetailBackLink
            to={backLinkTo ?? backTo}
            label={backLinkLabel ?? backLabel}
          />
          <Text className="text-[13px] text-gray-11">{missingCopy}</Text>
        </div>
      </div>
    );
  }

  return (
    <InboxReportStatusConfirmedContext.Provider value={statusConfirmed}>
      {trackTab && <ReportOpenTracker report={resolvedReport} tab={trackTab} />}
      {children(resolvedReport)}
    </InboxReportStatusConfirmedContext.Provider>
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
  if (backTo === "/inbox/pulls") return "pulls";
  if (backTo === "/inbox/runs") return "runs";
  if (backTo === "/inbox/dismissed") return null;
  return "reports";
}

/**
 * Mounts only once a report is resolved, so the OPENED/CLOSED engagement events
 * bracket the time the detail body is actually on screen. Renders nothing.
 */
export function ReportOpenTracker({
  report,
  tab,
}: {
  report: SignalReport;
  tab: InboxDetailTab;
}) {
  useReportOpenTracker(report, tab);
  return null;
}
