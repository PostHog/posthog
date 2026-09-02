import {
  EnvelopeSimpleIcon,
  FunnelIcon,
  ListChecksIcon,
} from "@phosphor-icons/react";
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
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import type { ReactNode } from "react";

export interface ReportsInboxViewPresentationProps {
  reports: SignalReport[];
  triageReportCount: number;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  isError: boolean;
  isEmpty: boolean;
  hasActiveFilters: boolean;
  triageEnabled: boolean;
  filterControl: ReactNode;
  scopeControl: ReactNode;
  renderReport: (report: SignalReport) => ReactNode;
  onConfigureAgents: () => void;
  onEnterTriage: () => void;
  onClearFilters: () => void;
  onLoadMore: () => void;
  onRetry: () => void;
}

export function ReportsInboxViewPresentation({
  reports,
  triageReportCount,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  isError,
  isEmpty,
  hasActiveFilters,
  triageEnabled,
  filterControl,
  scopeControl,
  renderReport,
  onConfigureAgents,
  onEnterTriage,
  onClearFilters,
  onLoadMore,
  onRetry,
}: ReportsInboxViewPresentationProps): React.JSX.Element {
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
                onClick={onConfigureAgents}
              >
                Configure agents
              </Button>
            </PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Issues and opportunities found in your product, ready to review
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-4">
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            {filterControl}
            <div className="flex flex-wrap items-center justify-end gap-2">
              {triageEnabled && (
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        type="button"
                        variant="outline"
                        className="gap-2"
                        disabled={triageReportCount === 0}
                        onClick={onEnterTriage}
                      >
                        <ListChecksIcon />
                        Triage mode
                        <kbd className="rounded bg-(--gray-4) px-1.5 font-mono text-[12px] text-gray-11">
                          T
                        </kbd>
                      </Button>
                    }
                  />
                  <TooltipContent side="bottom">
                    Step through reports that need a decision, one at a time.
                    Open, create a PR, or dismiss each from the keyboard.
                  </TooltipContent>
                </Tooltip>
              )}
              {scopeControl}
            </div>
          </div>
          {isLoading && reports.length === 0 ? (
            <div aria-hidden className="flex flex-col gap-2 pt-2">
              {[70, 55, 80, 60].map((width) => (
                <div key={width} className="flex items-center gap-3 py-2">
                  <Skeleton className="h-4" style={{ width: `${width}%` }} />
                </div>
              ))}
            </div>
          ) : isError ? (
            <Empty className="mx-auto max-w-md flex-none border-0 py-12">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <EnvelopeSimpleIcon size={24} />
                </EmptyMedia>
                <EmptyTitle>Couldn't load reports</EmptyTitle>
                <EmptyDescription>
                  Try loading the inbox again.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button variant="outline" size="default" onClick={onRetry}>
                  Retry
                </Button>
              </EmptyContent>
            </Empty>
          ) : isEmpty ? (
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
                    onClick={onClearFilters}
                  >
                    Clear filters
                  </Button>
                </EmptyContent>
              )}
            </Empty>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                {reports.map((report) => renderReport(report))}
              </div>
              {isFetchingNextPage && (
                <div className="flex justify-center py-2">
                  <Spinner />
                </div>
              )}
              {hasNextPage && !isFetchingNextPage && (
                <div className="flex justify-center py-2">
                  <Button variant="outline" size="sm" onClick={onLoadMore}>
                    Load more
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
