import {
  createdWindowAfterSort,
  type InboxCreatedWindow,
  type InboxSortDirection,
  type InboxSortField,
  resolveInboxSort,
} from "@posthog/core/inbox/reportFiltering";
import { INBOX_MODEL_SORT_FLAG, INBOX_TIME_WINDOW_FLAG } from "@posthog/shared";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

const DEFAULT_INBOX_SORT = {
  field: "created_at",
  direction: "desc",
} as const satisfies { field: InboxSortField; direction: InboxSortDirection };

export interface InboxActiveSort {
  sortField: InboxSortField;
  sortDirection: InboxSortDirection;
  createdWindow: InboxCreatedWindow | null;
  /** Staff with the model-sort flag, the same rule the API applies to ranking orderings. */
  modelSortAvailable: boolean;
  timeWindowAvailable: boolean;
  /** Stores a sort the user picked. A model sort also sets the default created-in window when none is set. */
  selectSort: (field: InboxSortField, direction: InboxSortDirection) => void;
}

/**
 * The sort and created-in window the list requests. A stored model sort or
 * window does nothing while its gate is closed, so a value persisted earlier
 * cannot break or narrow a list that has no control for it.
 */
export function useInboxActiveSort(): InboxActiveSort {
  const storedSortField = useInboxSignalsFilterStore((s) => s.sortField);
  const storedSortDirection = useInboxSignalsFilterStore(
    (s) => s.sortDirection,
  );
  const storedCreatedWindow = useInboxSignalsFilterStore(
    (s) => s.createdWindow,
  );
  const setSort = useInboxSignalsFilterStore((s) => s.setSort);
  const setCreatedWindow = useInboxSignalsFilterStore(
    (s) => s.setCreatedWindow,
  );
  const modelSortFlag = useFeatureFlag(INBOX_MODEL_SORT_FLAG);
  const timeWindowAvailable = useFeatureFlag(INBOX_TIME_WINDOW_FLAG);
  const { data: currentUser } = useMeQuery();
  const modelSortAvailable = modelSortFlag && currentUser?.is_staff === true;

  const sort = resolveInboxSort(
    { field: storedSortField, direction: storedSortDirection },
    modelSortAvailable,
    DEFAULT_INBOX_SORT,
  );

  return {
    sortField: sort.field,
    sortDirection: sort.direction,
    createdWindow: timeWindowAvailable ? storedCreatedWindow : null,
    modelSortAvailable,
    timeWindowAvailable,
    selectSort: (field, direction) => {
      setSort(field, direction);
      setCreatedWindow(
        createdWindowAfterSort(field, storedCreatedWindow, timeWindowAvailable),
      );
    },
  };
}
