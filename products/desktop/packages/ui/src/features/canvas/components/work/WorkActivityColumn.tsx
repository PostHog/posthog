import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";
import { openActivityItem } from "@posthog/ui/features/canvas/components/openActivityItem";
import { closeWorkActivity } from "@posthog/ui/features/canvas/stores/workActivityStore";

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
