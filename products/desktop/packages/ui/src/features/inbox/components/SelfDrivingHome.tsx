import { EnvelopeSimpleIcon } from "@phosphor-icons/react";
import { groupReportsForTriage } from "@posthog/core/inbox/reportTriage";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { AgentRunCard } from "@posthog/ui/features/inbox/components/AgentRunCard";
import { CardSkeleton } from "@posthog/ui/features/inbox/components/CardSkeleton";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { InboxBulkSelectionBar } from "@posthog/ui/features/inbox/components/InboxBulkSelectionBar";
import { InboxLoadMore } from "@posthog/ui/features/inbox/components/InboxLoadMore";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { InboxSearchFilterBar } from "@posthog/ui/features/inbox/components/InboxSearchFilterBar";
import { PullRequestCard } from "@posthog/ui/features/inbox/components/PullRequestCard";
import { PullRequestsBatchProvider } from "@posthog/ui/features/inbox/components/PullRequestsTab";
import { ReportCard } from "@posthog/ui/features/inbox/components/ReportCard";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import {
  buildSuppressDisabledReasonMap,
  useInboxBulkActions,
} from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportListSelection } from "@posthog/ui/features/inbox/hooks/useInboxReportListSelection";
import { Link } from "@tanstack/react-router";
import {
  type ComponentType,
  type MouseEvent,
  useCallback,
  useMemo,
  useState,
} from "react";

interface DismissibleCardProps {
  report: SignalReport;
  isSelected: boolean;
  onRowClick: (event: MouseEvent) => void;
  onDismiss: () => void;
  dismissDisabledReason: string | null;
  isDismissPending: boolean;
}

/**
 * The Self-Driving home: every live report on one page, grouped by what it
 * asks of the reader instead of by pipeline stage. Replaces the four inbox
 * tabs (behind the flag): "Needs your decision" leads, implementation in
 * flight follows, then what the agent is still working on, then FYIs.
 * Archived and resolved reports stay behind the Archive route.
 */
export function SelfDrivingHome() {
  const {
    scopedReports,
    allReports,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInboxAllReports();
  const [dismissReport, setDismissReport] = useState<SignalReport | null>(null);

  const grouped = useMemo(
    () => groupReportsForTriage(scopedReports),
    [scopedReports],
  );
  const triagedReports = useMemo(
    () => [
      ...grouped.decision,
      ...grouped.review,
      ...grouped.inProgress,
      ...grouped.fyi,
    ],
    [grouped],
  );
  const orderedReportIds = useMemo(
    () => triagedReports.map((report) => report.id),
    [triagedReports],
  );

  const {
    orderedSelectedIds,
    selectedCount,
    isReportSelected,
    handleReportClick,
    clearSelection,
  } = useInboxReportListSelection(orderedReportIds);

  const suppressDisabledByReportId = useMemo(
    () => buildSuppressDisabledReasonMap(allReports),
    [allReports],
  );

  const dismissTargetId = dismissReport?.id ?? null;
  const dismissBulkActions = useInboxBulkActions(
    allReports,
    dismissTargetId,
    "list_row",
  );

  const handleDismissDialogOpenChange = useCallback((open: boolean) => {
    if (!open) setDismissReport(null);
  }, []);

  const handleDismissConfirm = useCallback(
    async (result: DismissReportDialogResult) => {
      if (dismissTargetId == null) return;
      const isSnooze = isDismissalReasonSnooze(result.reason);
      const ok = isSnooze
        ? await dismissBulkActions.snoozeSelected()
        : await dismissBulkActions.suppressSelected(result);
      if (ok) {
        setDismissReport(null);
      }
    },
    [dismissBulkActions, dismissTargetId],
  );

  const dismissMutationPending =
    dismissReport != null &&
    (dismissBulkActions.isSuppressing || dismissBulkActions.isSnoozing);

  const renderDismissibleCard = useCallback(
    (Card: ComponentType<DismissibleCardProps>, report: SignalReport) => (
      <Card
        key={report.id}
        report={report}
        isSelected={isReportSelected(report.id)}
        onRowClick={(event) => handleReportClick(report.id, event)}
        onDismiss={() => setDismissReport(report)}
        dismissDisabledReason={
          suppressDisabledByReportId.get(report.id) ?? null
        }
        isDismissPending={
          dismissTargetId === report.id && dismissMutationPending
        }
      />
    ),
    [
      isReportSelected,
      handleReportClick,
      suppressDisabledByReportId,
      dismissMutationPending,
      dismissTargetId,
    ],
  );

  const listShellClassName =
    "@container mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-4";

  if (isLoading && scopedReports.length === 0) {
    return (
      <div className={listShellClassName}>
        <div className="flex items-center justify-between gap-3">
          <h1 className="font-semibold text-[15px] text-gray-12">
            Self-driving
          </h1>
          <div className="flex items-center gap-2.5">
            <Link
              to="/code/inbox/dismissed"
              className="text-[12px] text-gray-10 hover:text-gray-12 hover:underline"
            >
              Archive
            </Link>
            <InboxScopeSelect />
          </div>
        </div>
        <InboxSearchFilterBar searchPlaceholder="Search reports…" />
        <CardSkeleton count={4} variant="cards" />
      </div>
    );
  }

  const isEmpty = triagedReports.length === 0 && !hasNextPage;

  return (
    <>
      <div className={listShellClassName}>
        <div className="flex items-center justify-between gap-3">
          <h1 className="font-semibold text-[15px] text-gray-12">
            Self-driving
          </h1>
          <div className="flex items-center gap-2.5">
            <Link
              to="/code/inbox/dismissed"
              className="text-[12px] text-gray-10 hover:text-gray-12 hover:underline"
            >
              Archive
            </Link>
            <InboxScopeSelect />
          </div>
        </div>
        <InboxSearchFilterBar searchPlaceholder="Search reports…" />

        {selectedCount > 0 ? (
          <InboxBulkSelectionBar
            reports={allReports}
            selectedReportIds={orderedSelectedIds}
            onClearSelection={clearSelection}
          />
        ) : null}

        {isEmpty ? (
          <Empty className="mx-auto max-w-md py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <EnvelopeSimpleIcon size={24} />
              </EmptyMedia>
              <EmptyTitle>Nothing needs you right now</EmptyTitle>
              <EmptyDescription>
                Reports show up here as your agents find things worth acting on.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            <TriageSection
              title="Needs your decision"
              count={grouped.decision.length}
            >
              {grouped.decision.map((report) =>
                renderDismissibleCard(ReportCard, report),
              )}
            </TriageSection>

            {grouped.review.length > 0 && (
              <TriageSection title="Review" count={grouped.review.length}>
                <PullRequestsBatchProvider reports={grouped.review}>
                  {grouped.review.map((report) =>
                    renderDismissibleCard(PullRequestCard, report),
                  )}
                </PullRequestsBatchProvider>
              </TriageSection>
            )}

            {grouped.inProgress.length > 0 && (
              <TriageSection
                title="Agent working"
                count={grouped.inProgress.length}
              >
                {grouped.inProgress.map((report) => (
                  <AgentRunCard key={report.id} report={report} />
                ))}
              </TriageSection>
            )}

            {grouped.fyi.length > 0 && (
              <TriageSection
                title="For your awareness"
                count={grouped.fyi.length}
              >
                {grouped.fyi.map((report) =>
                  renderDismissibleCard(ReportCard, report),
                )}
              </TriageSection>
            )}

            <InboxLoadMore
              hasNextPage={hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              onLoadMore={() => void fetchNextPage({ cancelRefetch: false })}
            />
          </>
        )}
      </div>

      {dismissReport && (
        <DismissReportDialog
          open
          onOpenChange={handleDismissDialogOpenChange}
          report={dismissReport}
          isSubmitting={dismissMutationPending}
          snoozeDisabledReason={dismissBulkActions.snoozeDisabledReason}
          onConfirm={handleDismissConfirm}
        />
      )}
    </>
  );
}

// A group of cards under its state heading. "Needs your decision" renders
// even when empty (the page's whole question deserves an explicit "none");
// the other sections only render with content.
function TriageSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <h2 className="flex items-baseline gap-2 font-semibold text-[13px] text-gray-12">
        {title}
        <span className="font-normal text-[12px] text-gray-10 tabular-nums">
          {count}
        </span>
      </h2>
      {count === 0 ? (
        <p className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-4 py-3 text-[12.5px] text-gray-10">
          Nothing waiting on you.
        </p>
      ) : (
        <div className="flex flex-col gap-3">{children}</div>
      )}
    </section>
  );
}
