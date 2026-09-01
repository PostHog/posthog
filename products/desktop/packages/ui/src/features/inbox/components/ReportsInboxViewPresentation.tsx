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
import { InboxReportSection } from "@posthog/ui/features/inbox/components/InboxReportSection";
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
  reviewAndMerge: SignalReport[];
  reviewAndMergeCount: number;
  needsPr: SignalReport[];
  needsPrCount: number;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  isEmpty: boolean;
  hasActiveFilters: boolean;
  triageEnabled: boolean;
  scopeControl: ReactNode;
  searchControl: ReactNode;
  resolvedSection?: ReactNode;
  renderReport: (report: SignalReport) => ReactNode;
  onConfigureAgents: () => void;
  onEnterTriage: () => void;
  onClearFilters: () => void;
}

export function ReportsInboxViewPresentation({
  reviewAndMerge,
  reviewAndMergeCount,
  needsPr,
  needsPrCount,
  isLoading,
  isFetchingNextPage,
  isEmpty,
  hasActiveFilters,
  triageEnabled,
  scopeControl,
  searchControl,
  resolvedSection,
  renderReport,
  onConfigureAgents,
  onEnterTriage,
  onClearFilters,
}: ReportsInboxViewPresentationProps): React.JSX.Element {
  const triageReportCount = reviewAndMerge.length + needsPr.length;

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
                Step through reports that need a decision, one at a time. Open,
                create a PR, or archive each from the keyboard.
              </TooltipContent>
            </Tooltip>
          )}
          {scopeControl}
        </div>
      </PageHeader>

      <div className="shrink-0 border-(--gray-5) border-b">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-2.5 px-6 py-3">
          {searchControl}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-4">
          {isLoading && reviewAndMerge.length === 0 && needsPr.length === 0 ? (
            <div aria-hidden className="flex flex-col gap-2 pt-2">
              {[70, 55, 80, 60].map((width) => (
                <div key={width} className="flex items-center gap-3 py-2">
                  <Skeleton className="h-4" style={{ width: `${width}%` }} />
                </div>
              ))}
            </div>
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
              <InboxReportSection
                title="Review and merge"
                reports={reviewAndMerge}
                count={reviewAndMergeCount}
                emptyNote="No pull requests open yet. Start one from a report below."
                renderReport={renderReport}
              />
              <InboxReportSection
                title="Needs a PR"
                reports={needsPr}
                count={needsPrCount}
                emptyNote="No reports are waiting for a pull request."
                renderReport={renderReport}
              />
              {isFetchingNextPage && (
                <div className="flex justify-center py-2">
                  <Spinner />
                </div>
              )}
              {resolvedSection}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
