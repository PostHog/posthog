import {
  ArchiveIcon,
  CaretDownIcon,
  CheckCircleIcon,
  EnvelopeSimpleIcon,
  FunnelIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  ListChecksIcon,
} from "@phosphor-icons/react";
import { humanizeIdentifier } from "@posthog/core/inbox/activityLog";
import {
  filterReportsBySearch,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
  INBOX_DISMISSED_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { partitionInboxReports } from "@posthog/core/inbox/reportInboxSections";
import { inboxReviewerScopeValue } from "@posthog/core/inbox/reportMembership";
import {
  deriveHeadline,
  humanizeReportTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { InboxSearchFilterBar } from "@posthog/ui/features/inbox/components/InboxSearchFilterBar";
import { ReportRestoreButton } from "@posthog/ui/features/inbox/components/ReportRestoreButton";
import { ReportTriageFocus } from "@posthog/ui/features/inbox/components/ReportTriageFocus";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";
import { useTrackReportsInboxViewed } from "@posthog/ui/features/inbox/hooks/useTrackReportsInboxViewed";
import {
  hasActiveInboxFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import {
  navigateToAgents,
  navigateToInboxReportDetail,
} from "@posthog/ui/router/navigationBridge";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

/** Rows shown per section before "Show more" — a scan, not a scroll. */
const SECTION_PREVIEW_LIMIT = 5;

/**
 * How many reports auto-paging will load before stopping and marking counts
 * incomplete ("+"). Bounds the page's cost on enormous projects while keeping
 * counts exact for realistic scoped populations.
 */
const AUTOPAGE_REPORT_LIMIT = 400;

/**
 * The global reports inbox groups actionable reports by whether a PR is ready
 * to review, with terminal reports available separately. The per-space sidebar
 * list stays the working set; this is everything else.
 */
export function ReportsInboxView() {
  const {
    scopedReports,
    allReports,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    searchQuery,
    scope,
    isSuccess,
    sourceProductFilter,
    priorityFilter,
  } = useInboxAllReports({
    statusFilter: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
    applySourceFilter: false,
  });
  const triageFocusEnabled = useTriageFocusEnabled();
  const triageOrigin = useInboxTriageOrigin();
  const navigate = useNavigate();
  const [focusMode, setFocusMode] = useState(() => triageOrigin !== null);

  const exitFocusMode = useCallback(() => {
    setFocusMode(false);
    if (!triageOrigin) return;
    void navigate({
      to: "/inbox/reports",
      replace: true,
      state: (previous) => ({
        ...previous,
        inboxTriageOrigin: undefined,
      }),
    });
  }, [navigate, triageOrigin]);

  const sections = useMemo(
    () => partitionInboxReports(scopedReports),
    [scopedReports],
  );
  // Section totals are server-side count queries — at this dataset's size the
  // loaded rows are always a window, so nothing user-facing counts them.
  // Search is the one exception: it's a client-side title match, so a
  // searching page counts its matching rows instead.
  const serverCounts = useInboxSectionCounts();
  const hasActiveFilters = useInboxSignalsFilterStore((state) =>
    hasActiveInboxFilters(state, {
      includePrFilter: false,
      includeSourceFilter: false,
    }),
  );
  const resetFilters = useInboxSignalsFilterStore((s) => s.resetFilters);
  const searchActive = searchQuery.trim().length > 0;
  const reviewAndMergeCount = searchActive
    ? sections.reviewAndMerge.length
    : serverCounts.reviewAndMerge;
  const needsPrCount = searchActive
    ? sections.needsPr.length
    : serverCounts.needsPr;
  const triageReports = useMemo(
    () => [...sections.reviewAndMerge, ...sections.needsPr],
    [sections.reviewAndMerge, sections.needsPr],
  );
  useTrackReportsInboxViewed({
    reports: triageReports,
    totalCount: reviewAndMergeCount + needsPrCount,
    isReady: isSuccess && !serverCounts.isLoading,
    sourceProductFilter,
    priorityFilter,
    searchQuery,
    scope: inboxReviewerScopeValue(scope),
  });

  // Keep paging rows in (capped) so the sections have bodies to render —
  // counts never depend on this; they come from the server queries above.
  useEffect(() => {
    if (
      !hasNextPage ||
      isFetchingNextPage ||
      isLoading ||
      // Bound on rows actually loaded, not on search matches: a narrow
      // search shrinks scopedReports and would otherwise page far past the cap.
      allReports.length >= AUTOPAGE_REPORT_LIMIT
    ) {
      return;
    }
    fetchNextPage();
  }, [
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    allReports.length,
    fetchNextPage,
  ]);

  // Triage mode from anywhere on the page, matching the button's advertised key.
  useEffect(() => {
    if (!triageFocusEnabled || focusMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "t" && triageReports.length > 0) {
        event.preventDefault();
        setFocusMode(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [triageFocusEnabled, focusMode, triageReports.length]);

  if (triageFocusEnabled && focusMode && !isLoading) {
    return (
      <div className="h-full min-h-0">
        <ReportTriageFocus
          reports={triageReports}
          allReports={allReports}
          scope={scope}
          hasActiveFilters={hasActiveFilters}
          initialReportId={triageOrigin?.reportId}
          onExit={exitFocusMode}
        />
      </div>
    );
  }

  const isEmpty = searchActive
    ? sections.reviewAndMerge.length === 0 && sections.needsPr.length === 0
    : !serverCounts.isLoading &&
      serverCounts.reviewAndMerge === 0 &&
      serverCounts.needsPr === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-1">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Self-driving</PageHeaderTitle>
            <PageHeaderActions>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => navigateToAgents()}
              >
                Configure agents
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Issues and opportunities found in your product, ready to review
          </PageHeaderDescription>
        </PageHeaderHeading>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {triageFocusEnabled && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    variant="outline"
                    className="gap-2"
                    disabled={triageReports.length === 0}
                    onClick={() => setFocusMode(true)}
                  >
                    <ListChecksIcon size={16} />
                    Triage mode
                    <kbd className="rounded bg-(--gray-4) px-1.5 font-mono text-[12px] text-gray-11">
                      T
                    </kbd>
                  </Button>
                }
              />
              <TooltipContent side="bottom">
                Step through reports that need a decision, one at a time. Open,
                create a PR, or archive each from the keyboard.
              </TooltipContent>
            </Tooltip>
          )}
          <InboxScopeSelect />
        </div>
      </PageHeader>

      {/* The filter bar stays pinned with the header; only the sections
          scroll. */}
      <div className="shrink-0 border-(--gray-5) border-b">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-2.5 px-6 py-3">
          <InboxSearchFilterBar
            searchPlaceholder="Search reports…"
            showSourceFilter={false}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-4">
          {isLoading && scopedReports.length === 0 ? (
            <div aria-hidden className="flex flex-col gap-2 pt-2">
              {[70, 55, 80, 60].map((width) => (
                <div key={width} className="flex items-center gap-3 py-2">
                  <Skeleton className="h-4" style={{ width: `${width}%` }} />
                </div>
              ))}
            </div>
          ) : (
            <>
              {isEmpty ? (
                <Empty className="mx-auto max-w-md flex-none border-0 py-12">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      {hasActiveFilters ? (
                        <FunnelIcon size={24} />
                      ) : (
                        <EnvelopeSimpleIcon size={24} />
                      )}
                    </EmptyMedia>
                    <EmptyTitle>
                      {hasActiveFilters
                        ? "No reports match your filters"
                        : "Nothing to review"}
                    </EmptyTitle>
                    <EmptyDescription>
                      {hasActiveFilters
                        ? "Clear the filters to check for hidden reports."
                        : "Reports show up here as your agents find things worth acting on."}
                    </EmptyDescription>
                  </EmptyHeader>
                  {hasActiveFilters && (
                    <EmptyContent>
                      <Button
                        variant="outline"
                        size="default"
                        onClick={() => resetFilters()}
                      >
                        Clear filters
                      </Button>
                    </EmptyContent>
                  )}
                </Empty>
              ) : (
                <>
                  <InboxSection
                    title="Review and merge"
                    reports={sections.reviewAndMerge}
                    count={reviewAndMergeCount}
                    emptyNote="No pull requests open yet. Start one from a report below."
                  />
                  <InboxSection
                    title="Needs a PR"
                    reports={sections.needsPr}
                    count={needsPrCount}
                    emptyNote="No reports are waiting for a pull request."
                  />
                  {isFetchingNextPage && (
                    <div className="flex justify-center py-2">
                      <Spinner />
                    </div>
                  )}
                </>
              )}
              {!isEmpty && (
                <ResolvedSection
                  searchQuery={searchQuery}
                  count={serverCounts.resolved}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Web keeps both actionable sections visible even when one is empty, which
// makes the PR/no-PR split legible without requiring reports in both states.
function InboxSection({
  title,
  reports,
  count,
  emptyNote,
}: {
  title: string;
  /** The loaded rows to render — a window; never what the header counts. */
  reports: SignalReport[];
  /** The section's true total, from a server-side count query. */
  count: number;
  emptyNote?: string;
}) {
  const [open, setOpen] = useState(true);
  const [visibleCount, setVisibleCount] = useState(SECTION_PREVIEW_LIMIT);
  if (count === 0 && reports.length === 0 && !emptyNote) return null;
  const visible = reports.slice(0, visibleCount);
  const hidden = reports.length - visible.length;
  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-2 rounded px-0.5 py-1 text-left"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        <span className="flex items-center gap-1 font-mono font-semibold text-[11px] text-gray-10 uppercase tracking-widest">
          {title}
          <span className="tabular-nums">({count})</span>
        </span>
        <div className="h-px flex-1 bg-(--gray-5)" />
        <CaretDownIcon
          size={12}
          className={`text-gray-9 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open &&
        (count === 0 && reports.length === 0 ? (
          <p className="px-1 py-2 text-[13.5px] text-gray-10">{emptyNote}</p>
        ) : (
          <div className="flex flex-col gap-1">
            {visible.map((report) => (
              <InboxReportRow key={report.id} report={report} />
            ))}
            {hidden > 0 && (
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                className="self-center text-gray-10"
                onClick={() =>
                  setVisibleCount((current) =>
                    Math.min(current + SECTION_PREVIEW_LIMIT, reports.length),
                  )
                }
              >
                Show more ({hidden})
              </Button>
            )}
          </div>
        ))}
    </section>
  );
}

function InboxReportRow({ report }: { report: SignalReport }) {
  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const products = (report.source_products ?? [])
    .map((product) => humanizeIdentifier(product).toLowerCase())
    .join(" · ");
  const headline = useMemo(
    () => deriveHeadline(report.summary),
    [report.summary],
  );
  const pr = report.implementation_pr_url
    ? parsePrUrl(report.implementation_pr_url)
    : null;
  const { pointerHandlers } = useInboxReportDetailPrefetch({
    to: "/inbox/reports/$reportId",
    params: { reportId: report.id },
  });
  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: A semantic button cannot contain the PR and restore buttons. */}
      <div
        role="button"
        tabIndex={0}
        {...pointerHandlers}
        onClick={() => navigateToInboxReportDetail(report.id)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            navigateToInboxReportDetail(report.id);
          }
        }}
        className="flex w-full cursor-pointer items-center gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2 text-left transition hover:border-(--gray-6) hover:bg-(--gray-2)"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate font-medium text-[14px] text-gray-12">
            {conventionalTitle && (
              <ConventionalCommitScopeTag
                type={conventionalTitle.type}
                scope={conventionalTitle.scope}
              />
            )}
            <span>{humanizeReportTitle(report.title, "Untitled report")}</span>
          </span>
          {headline && (
            <span className="line-clamp-2 text-[13px] text-gray-11">
              {headline}
            </span>
          )}
          <span className="flex items-center gap-1.5 text-[12.5px] text-gray-10">
            {products && <span className="truncate">{products}</span>}
            <RelativeTimestamp
              timestamp={report.created_at}
              className="shrink-0 text-[12.5px]"
            />
          </span>
        </div>
        <span className="flex shrink-0 items-center gap-2">
          {/* Terminal rows share one section, so each wears its end state:
              resolved closed itself when the fix shipped; archived was a
              person's call and carries their reason. */}
          {report.status === "resolved" && (
            <span
              title="The fix shipped and this report closed"
              className="flex items-center gap-1 rounded border border-(--green-6) bg-(--green-2) px-1.5 py-0.5 text-[12px] text-green-11"
            >
              <CheckCircleIcon size={11} />
              Shipped
            </span>
          )}
          {report.status === "suppressed" && (
            <span
              title={report.dismissal_note ?? undefined}
              className="flex items-center gap-1 rounded border border-(--gray-6) bg-(--gray-2) px-1.5 py-0.5 text-[12px] text-gray-11"
            >
              <ArchiveIcon size={11} />
              Archived
              {report.dismissal_reason
                ? ` · ${humanizeIdentifier(report.dismissal_reason)}`
                : ""}
            </span>
          )}
          <SuggestedReviewerAvatarStack report={report} />
          <SignalReportPriorityBadge priority={report.priority} />
          <span className="font-mono text-[13px] text-gray-11 tabular-nums">
            {report.signal_count} signal{report.signal_count === 1 ? "" : "s"}
          </span>
          {/* Acting on a row must not also open it. */}
          {/* biome-ignore lint/a11y/noStaticElementInteractions: propagation guard for the buttons inside, not interactive itself */}
          <span
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
            className="flex items-center gap-1.5"
          >
            {pr && (
              <button
                type="button"
                onClick={() => {
                  if (report.implementation_pr_url) {
                    openExternalUrl(report.implementation_pr_url);
                  }
                }}
                title={
                  report.implementation_pr_merged
                    ? "This report's earlier PR merged, but evidence kept arriving"
                    : "Open the pull request on GitHub"
                }
                className={
                  report.implementation_pr_merged
                    ? "flex items-center gap-1 rounded border border-(--gray-6) px-1.5 py-0.5 font-mono text-[12px] text-gray-11 hover:bg-(--gray-3) hover:text-gray-12"
                    : "flex items-center gap-1 rounded border border-(--accent-7) bg-(--accent-2) px-1.5 py-0.5 font-mono text-(--accent-11) text-[12px] hover:bg-(--accent-3)"
                }
              >
                {report.implementation_pr_merged ? (
                  <GitMergeIcon size={11} />
                ) : (
                  <GitPullRequestIcon size={11} />
                )}
                #{pr.number}
                {report.implementation_pr_merged ? " merged" : ""}
              </button>
            )}
            <ReportRestoreButton report={report} />
          </span>
        </span>
      </div>
    </>
  );
}

// Archived and resolved reports come from their own server-side fetch, so the
// section fetches lazily on first expand and stays collapsed by default.
function ResolvedSection({
  searchQuery,
  count,
}: {
  searchQuery: string;
  count: number;
}): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const {
    allReports,
    isLoading,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInboxReportsInfinite(
    { status: INBOX_DISMISSED_STATUS_FILTER, ordering: "-updated_at" },
    { enabled: expanded, pageSize: SECTION_PREVIEW_LIMIT },
  );
  const matchingReports = useMemo(
    () => filterReportsBySearch(allReports, searchQuery),
    [allReports, searchQuery],
  );
  const searchActive = searchQuery.trim().length > 0;
  const canAutoPageSearch =
    searchActive && hasNextPage && allReports.length < AUTOPAGE_REPORT_LIMIT;

  useEffect(() => {
    if (!expanded || !canAutoPageSearch || isFetchingNextPage) return;
    void fetchNextPage();
  }, [expanded, canAutoPageSearch, isFetchingNextPage, fetchNextPage]);

  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-2 rounded px-0.5 py-1 text-left"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-1 font-mono font-semibold text-[11px] text-gray-10 uppercase tracking-widest">
          Resolved <span className="tabular-nums">({count})</span>
        </span>
        <div className="h-px flex-1 bg-(--gray-5)" />
        <CaretDownIcon
          size={12}
          className={`text-gray-9 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>
      {expanded &&
        (isLoading ? (
          <div className="flex justify-center py-3">
            <Spinner />
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {matchingReports.length === 0 && !canAutoPageSearch && (
              <p className="px-1 py-2 text-[13.5px] text-gray-10">
                {searchActive
                  ? "No resolved or archived reports match your search. Try a different search."
                  : "Nothing resolved or archived yet."}
              </p>
            )}
            {matchingReports.map((report) => (
              <InboxReportRow key={report.id} report={report} />
            ))}
            {isFetchingNextPage && (
              <div className="flex justify-center py-2">
                <Spinner />
              </div>
            )}
            {hasNextPage && !canAutoPageSearch && (
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                className="self-center text-gray-10"
                disabled={isFetchingNextPage}
                onClick={() => fetchNextPage()}
              >
                {searchActive
                  ? "Show more"
                  : `Show more (${Math.max(0, count - matchingReports.length)})`}
              </Button>
            )}
          </div>
        ))}
    </section>
  );
}
