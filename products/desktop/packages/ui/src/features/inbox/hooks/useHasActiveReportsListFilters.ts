import { INBOX_TIME_WINDOW_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  hasActiveReportsListFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

/** Whether the reports list is filtered by a control its filter menu shows. */
export function useHasActiveReportsListFilters(): boolean {
  const timeWindowAvailable = useFeatureFlag(INBOX_TIME_WINDOW_FLAG);
  return useInboxSignalsFilterStore((state) =>
    hasActiveReportsListFilters(state, timeWindowAvailable),
  );
}
