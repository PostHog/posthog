import { ArrowRightIcon } from "@phosphor-icons/react";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { navigateToInboxReports } from "@posthog/ui/router/navigationBridge";
import type { ReactElement } from "react";
import { ActivityRowSurface } from "./ActivityRowSurface";

interface InboxActivityOverflowRowProps {
  count: number;
  onOpened?: () => void;
  asOption?: boolean;
  optionValue?: string;
}

export function InboxActivityOverflowRow({
  count,
  onOpened,
  asOption = false,
  optionValue,
}: InboxActivityOverflowRowProps): ReactElement {
  const inboxScope = useActivityFilterStore((state) => state.inboxScope);
  const sourceProductFilter = useActivityFilterStore(
    (state) => state.inboxSourceProductFilter,
  );
  const prFilter = useActivityFilterStore((state) => state.inboxPrFilter);
  const sortField = useActivityFilterStore((state) => state.inboxSortField);
  const sortDirection = useActivityFilterStore(
    (state) => state.inboxSortDirection,
  );
  const priorityFilter = useActivityFilterStore(
    (state) => state.inboxPriorityFilter,
  );
  const setScope = useInboxReviewerScopeStore((state) => state.setScope);
  const setSourceProductFilter = useInboxSignalsFilterStore(
    (state) => state.setSourceProductFilter,
  );
  const setPriorityFilter = useInboxSignalsFilterStore(
    (state) => state.setPriorityFilter,
  );
  const setPrFilter = useInboxSignalsFilterStore((state) => state.setPrFilter);
  const setSort = useInboxSignalsFilterStore((state) => state.setSort);

  const viewMore = (): void => {
    setScope(inboxScope);
    setSourceProductFilter(sourceProductFilter);
    setPrFilter(prFilter);
    setSort(sortField, sortDirection);
    setPriorityFilter(priorityFilter);
    navigateToInboxReports();
    onOpened?.();
  };

  return (
    <ActivityRowSurface
      type="button"
      asOption={asOption}
      optionValue={optionValue}
      left
      className="py-1.5 text-muted-foreground"
      onClick={viewMore}
    >
      <span className="w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate text-[13px]">
        View {count} more reports
      </span>
      <ArrowRightIcon size={13} className="shrink-0" />
    </ActivityRowSurface>
  );
}
