import { EnvelopeSimpleIcon } from "@phosphor-icons/react";
import { groupReportsByAge } from "@posthog/core/inbox/reportAgeGroups";
import {
  Autocomplete,
  AutocompleteList,
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { Fragment, type ReactElement, type ReactNode, useMemo } from "react";

export interface InboxPanePresentationProps {
  reports: SignalReport[];
  query: string;
  onQueryChange: (query: string) => void;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  hasActiveFilters: boolean;
  /** Runs the age buckets the other way, so the list reads oldest first. */
  oldestFirst: boolean;
  filterControl: ReactNode;
  renderReport: (report: SignalReport) => ReactNode;
  onClearFilters: () => void;
  onLoadMore: () => void;
  className?: string;
}

/**
 * The rail's Self-driving column: a permanently open inline Autocomplete, so
 * the search box keeps focus while the arrows walk the reports under it. Same
 * shape as the Activity feed and the canvases list beside it.
 */
export function InboxPanePresentation({
  reports,
  query,
  onQueryChange,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  hasActiveFilters,
  oldestFirst,
  filterControl,
  renderReport,
  onClearFilters,
  onLoadMore,
  className,
}: InboxPanePresentationProps): ReactElement {
  const isSearching = query.trim() !== "";
  const optionValues = reports.map((report) => report.id);
  const groups = useMemo(
    () => groupReportsByAge(reports, { oldestFirst }),
    [reports, oldestFirst],
  );

  return (
    <Autocomplete<string>
      inline
      open
      value={query}
      items={optionValues}
      filter={null}
      onValueChange={(value, eventDetails) => {
        if (
          eventDetails.reason === "input-change" &&
          typeof value === "string"
        ) {
          onQueryChange(value);
        }
      }}
    >
      <div className={cn("flex min-h-0 flex-col", className)}>
        <SidebarSearchHeader
          title="Self-driving"
          query={query}
          placeholder="Search reports…"
          searchLabel="Search reports"
          onClear={() => onQueryChange("")}
          actions={filterControl}
        />
        <AutocompleteList className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !p-1.5 min-h-0 flex-1 overflow-y-auto">
          {isLoading && reports.length === 0 ? (
            <LoadingState className="py-10" />
          ) : reports.length === 0 ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <EnvelopeSimpleIcon />
                </EmptyMedia>
                <EmptyTitle>
                  {isSearching
                    ? "No matching reports"
                    : hasActiveFilters
                      ? "No reports match your filters"
                      : "Nothing to review"}
                </EmptyTitle>
                <EmptyDescription>
                  {isSearching
                    ? "Try a different search."
                    : hasActiveFilters
                      ? "Clear the filters to check for hidden reports."
                      : "Reports show up here as your agents find things worth acting on."}
                </EmptyDescription>
              </EmptyHeader>
              {!isSearching && hasActiveFilters && (
                <EmptyContent>
                  <Button variant="outline" size="sm" onClick={onClearFilters}>
                    Clear filters
                  </Button>
                </EmptyContent>
              )}
            </Empty>
          ) : (
            <div className="flex flex-col gap-px">
              {groups.map((group) => (
                <Fragment key={group.label}>
                  <MenuLabel>{group.label}</MenuLabel>
                  {group.reports.map((report) => renderReport(report))}
                </Fragment>
              ))}
            </div>
          )}
          {hasNextPage && (
            <div className="flex justify-center py-2">
              <Button
                variant="outline"
                size="sm"
                disabled={isFetchingNextPage}
                onClick={onLoadMore}
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </AutocompleteList>
      </div>
    </Autocomplete>
  );
}
