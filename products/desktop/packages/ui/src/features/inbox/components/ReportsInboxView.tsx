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
  INBOX_DISMISSED_STATUS_FILTER,
  REPORTS_INBOX_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { partitionInboxReports } from "@posthog/core/inbox/reportInboxSections";
import {
  deriveHeadline,
  humanizeReportTitle,
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
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { InboxSearchFilterBar } from "@posthog/ui/features/inbox/components/InboxSearchFilterBar";
import { ReportRestoreButton } from "@posthog/ui/features/inbox/components/ReportRestoreButton";
import { ReportTriageFocus } from "@posthog/ui/features/inbox/components/ReportTriageFocus";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";
import {
  hasActiveInboxFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
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
import { useEffect, useMemo, useState } from "react";

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
 * The global reports inbox: every report in the project on one page,
 * sectioned by what it asks (a decision, or just watching), quantified by the
 * evidence behind it, and triageable one at a time in focus mode. The
 * per-space sidebar list stays the working set; this is everything else.
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
  } = useInboxAllReports({
    statusFilter: REPORTS_INBOX_STATUS_FILTER,
    applyPrFilter: true,
  });
  const triageFocusEnabled = useTriageFocusEnabled();
  const [focusMode, setFocusMode] = useState(false);

  const sections = useMemo(
    () => partitionInboxReports(scopedReports),
    [scopedReports],
  );
  // Section totals are server-side count queries — at this dataset's size the
  // loaded rows are always a window, so nothing user-facing counts them.
  // Search is the one exception: it's a client-side title match, so a
  // searching page counts its matching rows instead.
  const serverCounts = useInboxSectionCounts();
  const prFilter = useInboxSignalsFilterStore((s) => s.prFilter);
  const hasActiveFilters = useInboxSignalsFilterStore(hasActiveInboxFilters);
  const resetFilters = useInboxSignalsFilterStore((s) => s.resetFilters);
  const searchActive = searchQuery.trim().length > 0;
  const decisionCount = searchActive
    ? sections.decision.length
    : serverCounts.decision;
  const monitoringCount = searchActive
    ? sections.monitoring.length
    : serverCounts.monitoring;

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
      if (event.key === "t" && sections.decision.length > 0) {
        event.preventDefault();
        setFocusMode(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [triageFocusEnabled, focusMode, sections.decision.length]);

  if (triageFocusEnabled && focusMode) {
    return (
      <div className="h-full min-h-0 overflow-y-auto">
        <ReportTriageFocus
          reports={sections.decision}
          allReports={allReports}
          onExit={() => setFocusMode(false)}
        />
      </div>
    );
  }

  const isEmpty = searchActive
    ? sections.decision.length === 0 && sections.monitoring.length === 0
    : !serverCounts.isLoading &&
      serverCounts.decision === 0 &&
      serverCounts.monitoring === 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-1">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Self-driving</PageHeaderTitle>
            {serverCounts.decision > 0 && (
              <PageHeaderChip
                icon={<EnvelopeSimpleIcon size={12} weight="fill" />}
              >
                {serverCounts.decision} need
                {serverCounts.decision === 1 ? "s" : ""} a decision
              </PageHeaderChip>
            )}
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
                    disabled={sections.decision.length === 0}
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
                Step through reports that need a decision, one at a time. Fix,
                defer, or archive each with a single key.
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
            showPrFilter
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
                <Empty className="mx-auto max-w-md py-16">
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
                    title="Needs a decision"
                    reports={sections.decision}
                    count={decisionCount}
                    caption={
                      !searchActive &&
                      prFilter === "all" &&
                      serverCounts.decisionPr > 0
                        ? `${serverCounts.decisionPr} with a PR to review`
                        : undefined
                    }
                    emptyNote="Nothing waiting on you."
                  />
                  <InboxSection
                    title="Monitoring"
                    reports={sections.monitoring}
                    count={monitoringCount}
                  />
                  {isFetchingNextPage && (
                    <div className="flex justify-center py-2">
                      <Spinner />
                    </div>
                  )}
                </>
              )}
              <ResolvedSection />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// A section header + capped rows. "Needs a decision" renders even when empty
// (the page's whole question deserves an explicit answer); others only with
// content.
function InboxSection({
  title,
  reports,
  count,
  caption,
  emptyNote,
}: {
  title: string;
  /** The loaded rows to render — a window; never what the header counts. */
  reports: SignalReport[];
  /** The section's true total, from a server-side count query. */
  count: number;
  /** Secondary breakdown shown after the count (e.g. "37 with a PR to review"). */
  caption?: string;
  emptyNote?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  if (count === 0 && reports.length === 0 && !emptyNote) return null;
  const visible = expanded ? reports : reports.slice(0, SECTION_PREVIEW_LIMIT);
  const hidden = reports.length - visible.length;
  return (
    <section className="flex flex-col gap-1.5">
      <h2 className="flex items-baseline gap-2 border-(--gray-5) border-b pb-1 font-medium text-[12px] text-gray-10 uppercase tracking-wide">
        {title}
        <span className="tabular-nums">({count})</span>
        {caption && (
          <span className="font-normal normal-case tracking-normal">
            · {caption}
          </span>
        )}
      </h2>
      {count === 0 && reports.length === 0 ? (
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
              onClick={() => setExpanded(true)}
            >
              Show more ({hidden})
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

// A row carries what the old inbox's cards proved useful: the humanized
// title, one line of the summary's tl;dr (deciding without opening), where it
// came from, reviewers, the PR when there is one, and archive on hover — at
// row density rather than card height.
function InboxReportRow({ report }: { report: SignalReport }) {
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
  const { actionButton: archiveButton, dialog: archiveDialog } =
    useInboxReportDismissAction(report);
  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: the row holds a real archive <button>, which a <button> row would illegally nest */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => navigateToInboxReportDetail(report.id)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            navigateToInboxReportDetail(report.id);
          }
        }}
        className="group flex w-full cursor-pointer items-center gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2 text-left transition hover:border-(--gray-6) hover:bg-(--gray-2)"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-center gap-1.5">
            <span className="truncate font-medium text-[14px] text-gray-12">
              {humanizeReportTitle(report.title, "Untitled report")}
            </span>
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
            {report.implementation_pr_url &&
              !report.implementation_pr_merged && (
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={() => navigateToInboxReportDetail(report.id)}
                >
                  Review
                </Button>
              )}
            <ReportRestoreButton report={report} />
            {report.status !== "suppressed" && (
              <span className="opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                {archiveButton}
              </span>
            )}
          </span>
        </span>
      </div>
      {archiveDialog}
    </>
  );
}

// Archived and resolved reports come from their own server-side fetch, so the
// section fetches lazily on first expand and stays collapsed by default.
function ResolvedSection() {
  const [expanded, setExpanded] = useState(false);
  const {
    allReports,
    isLoading,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInboxReportsInfinite(
    { status: INBOX_DISMISSED_STATUS_FILTER, ordering: "-updated_at" },
    { enabled: expanded, pageSize: 25 },
  );
  return (
    <section className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-baseline gap-2 border-(--gray-5) border-b pb-1 text-left font-medium text-[12px] text-gray-10 uppercase tracking-wide"
      >
        Resolved & archived
        <CaretDownIcon
          size={11}
          className={expanded ? "rotate-180 self-center" : "self-center"}
        />
      </button>
      {expanded &&
        (isLoading ? (
          <div className="flex justify-center py-3">
            <Spinner />
          </div>
        ) : allReports.length === 0 ? (
          <p className="px-1 py-2 text-[13.5px] text-gray-10">
            Nothing resolved or archived yet.
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {allReports.map((report) => (
              <InboxReportRow key={report.id} report={report} />
            ))}
            {hasNextPage && (
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                className="self-center text-gray-10"
                disabled={isFetchingNextPage}
                onClick={() => fetchNextPage()}
              >
                {isFetchingNextPage ? <Spinner /> : "Show more"}
              </Button>
            )}
          </div>
        ))}
    </section>
  );
}
