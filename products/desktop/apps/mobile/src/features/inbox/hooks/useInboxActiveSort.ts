import {
  createdWindowAfterSort,
  type InboxCreatedWindow,
  type InboxSortDirection,
  type InboxSortField,
  resolveInboxSort,
} from "@posthog/core/inbox/reportFiltering";
import { INBOX_MODEL_SORT_FLAG, INBOX_TIME_WINDOW_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "posthog-react-native";
import { useUserQuery } from "@/features/auth";
import { useInboxFilterStore } from "../stores/inboxFilterStore";

const DEFAULT_INBOX_SORT = {
  field: "priority",
  direction: "asc",
} as const satisfies { field: InboxSortField; direction: InboxSortDirection };

/**
 * The sort and created-in window the list requests. A stored model sort or
 * window does nothing while its gate is closed, so a value persisted earlier
 * cannot break or narrow a list that has no control for it.
 */
export function useInboxActiveSort(): {
  sortField: InboxSortField;
  sortDirection: InboxSortDirection;
  createdWindow: InboxCreatedWindow | null;
  /** Staff with the model-sort flag, the same rule the API applies to ranking orderings. */
  modelSortAvailable: boolean;
  timeWindowAvailable: boolean;
  /** Stores a sort the user picked. A model sort also sets the default created-in window when none is set. */
  selectSort: (field: InboxSortField, direction: InboxSortDirection) => void;
} {
  const storedSortField = useInboxFilterStore((s) => s.sortField);
  const storedSortDirection = useInboxFilterStore((s) => s.sortDirection);
  const storedCreatedWindow = useInboxFilterStore((s) => s.createdWindow);
  const setSort = useInboxFilterStore((s) => s.setSort);
  const setCreatedWindow = useInboxFilterStore((s) => s.setCreatedWindow);
  const modelSortFlag = !!useFeatureFlag(INBOX_MODEL_SORT_FLAG);
  const timeWindowAvailable = !!useFeatureFlag(INBOX_TIME_WINDOW_FLAG);
  const { data: userData } = useUserQuery();
  const modelSortAvailable = modelSortFlag && userData?.is_staff === true;

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
