import { filterReportsBySearch } from "@posthog/core/inbox/reportFiltering";
import { Spinner } from "@posthog/quill";
import type { SignalReportStatus } from "@posthog/shared/types";
import { InboxReportRow } from "@posthog/ui/features/inbox/components/InboxReportRow";
import { InboxReportSection } from "@posthog/ui/features/inbox/components/InboxReportSection";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useEffect, useMemo, useState } from "react";

const SECTION_PREVIEW_LIMIT = 5;
const AUTOPAGE_REPORT_LIMIT = 400;

export function ResolvedReportsSection({
  searchQuery,
  statuses,
  count,
}: {
  searchQuery: string;
  statuses: Extract<SignalReportStatus, "resolved" | "suppressed">[];
  count: number;
}): React.JSX.Element | null {
  const [expanded, setExpanded] = useState(false);
  const {
    allReports,
    isLoading,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInboxReportsInfinite(
    { status: statuses.join(","), ordering: "-updated_at" },
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

  if (count === 0) return null;

  const includesResolved = statuses.includes("resolved");
  const includesDismissed = statuses.includes("suppressed");
  const title = includesResolved
    ? includesDismissed
      ? "Resolved and dismissed"
      : "Resolved"
    : "Dismissed";

  return (
    <>
      <InboxReportSection
        title={title}
        reports={matchingReports}
        count={count}
        defaultOpen={false}
        isLoading={expanded && isLoading}
        emptyNote={
          searchActive
            ? `No ${title.toLowerCase()} reports match your search. Try a different search.`
            : `Nothing ${title.toLowerCase()} yet.`
        }
        renderReport={(report) => (
          <InboxReportRow key={report.id} report={report} />
        )}
        onOpenChange={setExpanded}
        onShowMore={
          hasNextPage && !canAutoPageSearch
            ? () => void fetchNextPage()
            : undefined
        }
      />
      {isFetchingNextPage && (
        <div className="flex justify-center py-2">
          <Spinner />
        </div>
      )}
    </>
  );
}
