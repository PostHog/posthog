import type { IconProps } from "@phosphor-icons/react";
import {
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
} from "@posthog/core/inbox/reportMembership";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { CardSkeleton } from "@posthog/ui/features/inbox/components/CardSkeleton";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { InboxBulkSelectionBar } from "@posthog/ui/features/inbox/components/InboxBulkSelectionBar";
import { InboxLoadMore } from "@posthog/ui/features/inbox/components/InboxLoadMore";
import { InboxSearchFilterBar } from "@posthog/ui/features/inbox/components/InboxSearchFilterBar";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import {
  buildSuppressDisabledReasonMap,
  useInboxBulkActions,
} from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useInboxReportListSelection } from "@posthog/ui/features/inbox/hooks/useInboxReportListSelection";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { Flex } from "@radix-ui/themes";
import {
  type ComponentType,
  Fragment,
  type MouseEvent,
  type ReactNode,
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

export interface InboxReportListTabEmptyState {
  Icon: ComponentType<IconProps>;
  /** Title shown when the scope is "For you". */
  forYouTitle: string;
  /** Title shown when the scope is "Entire project". */
  entireProjectTitle: string;
  /** Title shown when the scope is a specific teammate. */
  teammateTitle: string;
  description: string;
}

interface InboxReportListTabProps {
  /** Tab membership filter, applied on top of the scope-filtered list. */
  predicate: (report: SignalReport) => boolean;
  /** Per-card renderer; receives dismiss wiring from this shell. */
  Card: ComponentType<DismissibleCardProps>;
  searchPlaceholder: string;
  emptyState: InboxReportListTabEmptyState;
  /**
   * Optional wrapper around the rendered card list. Receives the tab-matching
   * reports so tab-specific providers (e.g. the PR diff stats batch) can
   * fetch in bulk once for the visible page instead of per-card.
   */
  CardListWrapper?: ComponentType<{
    reports: SignalReport[];
    children: ReactNode;
  }>;
  /**
   * Fetch a server-filtered PR-only list instead of the broad pipeline list, so
   * the tab body comes from the same source as the Pull-requests count (a PR
   * past the broad list's first page would otherwise not render).
   */
  pullRequestsOnly?: boolean;
}

/**
 * Shared shell for inbox tabs that list dismissible reports (Pull requests and
 * Reports). Owns the dismiss dialog state machine and the search/skeleton/empty
 * layout so individual tabs only configure their predicate + card + copy.
 *
 * Runs tab keeps its own component because it shows a non-dismissible card and
 * a distinct in-progress header section, not a flat dismissible list.
 */
export function InboxReportListTab({
  predicate,
  Card,
  searchPlaceholder,
  emptyState,
  CardListWrapper,
  pullRequestsOnly = false,
}: InboxReportListTabProps) {
  const {
    scopedReports,
    allReports,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInboxAllReports({
    pullRequestsOnly,
  });
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const [dismissReport, setDismissReport] = useState<SignalReport | null>(null);

  const matchingReports = useMemo(
    () => scopedReports.filter(predicate),
    [scopedReports, predicate],
  );

  const orderedReportIds = useMemo(
    () => matchingReports.map((report) => report.id),
    [matchingReports],
  );

  const {
    orderedSelectedIds,
    selectedCount,
    isReportSelected,
    handleReportClick,
    clearSelection,
  } = useInboxReportListSelection(orderedReportIds);

  // Build the disabled-reason lookup once per render so each card is O(1).
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

  const emptyTitle = resolveEmptyTitle(scope, emptyState);
  const EmptyIcon = emptyState.Icon;

  if (isLoading && scopedReports.length === 0) {
    return (
      <Flex direction="column" gap="4" className="mx-auto max-w-4xl px-6 py-4">
        <InboxSearchFilterBar searchPlaceholder={searchPlaceholder} />
        <CardSkeleton count={4} variant="cards" />
      </Flex>
    );
  }

  return (
    <>
      <Flex direction="column" gap="4" className="mx-auto max-w-4xl px-6 py-4">
        <InboxSearchFilterBar searchPlaceholder={searchPlaceholder} />

        {selectedCount > 0 ? (
          <InboxBulkSelectionBar
            reports={allReports}
            selectedReportIds={orderedSelectedIds}
            onClearSelection={clearSelection}
          />
        ) : null}

        {matchingReports.length === 0 && !hasNextPage ? (
          <Empty className="mx-auto max-w-md py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <EmptyIcon size={24} />
              </EmptyMedia>
              <EmptyTitle>{emptyTitle}</EmptyTitle>
              <EmptyDescription>{emptyState.description}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            {matchingReports.length > 0 && (
              <CardListContainer
                reports={matchingReports}
                Wrapper={CardListWrapper}
              >
                <Flex direction="column" gap="3">
                  {matchingReports.map((report) => (
                    <Card
                      key={report.id}
                      report={report}
                      isSelected={isReportSelected(report.id)}
                      onRowClick={(event) =>
                        handleReportClick(report.id, event)
                      }
                      onDismiss={() => setDismissReport(report)}
                      dismissDisabledReason={
                        suppressDisabledByReportId.get(report.id) ?? null
                      }
                      isDismissPending={
                        dismissReport?.id === report.id &&
                        dismissMutationPending
                      }
                    />
                  ))}
                </Flex>
              </CardListContainer>
            )}
            <InboxLoadMore
              hasNextPage={hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              onLoadMore={() => void fetchNextPage({ cancelRefetch: false })}
            />
          </>
        )}
      </Flex>

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

function CardListContainer({
  reports,
  Wrapper,
  children,
}: {
  reports: SignalReport[];
  Wrapper?: ComponentType<{ reports: SignalReport[]; children: ReactNode }>;
  children: ReactNode;
}) {
  if (!Wrapper) return <Fragment>{children}</Fragment>;
  return <Wrapper reports={reports}>{children}</Wrapper>;
}

function resolveEmptyTitle(
  scope: string,
  emptyState: InboxReportListTabEmptyState,
): string {
  if (scope === INBOX_SCOPE_FOR_YOU) return emptyState.forYouTitle;
  if (scope === INBOX_SCOPE_ENTIRE_PROJECT)
    return emptyState.entireProjectTitle;
  return emptyState.teammateTitle;
}
