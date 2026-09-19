import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { closeWorkActivity } from "@posthog/ui/features/canvas/stores/workActivityStore";

/**
 * The notification center: the activity feed as a column that opens over the
 * Work column. A row opens its session in the tab you are in and marks itself
 * read; the column closes behind it, since the thing it pointed at is now on
 * screen.
 */
export function WorkActivityColumn({ className }: { className?: string }) {
  return (
    <ActivityFeedList
      className={className}
      onActivate={(item) => {
        openActivityItem(item);
        closeWorkActivity();
      }}
      onOpened={closeWorkActivity}
    />
  );
}
