import { Label, Switch } from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { track } from "@posthog/ui/shell/analytics";
import { useId } from "react";

/** Narrows both Activity surfaces down to what hasn't been read yet. */
export function ActivityUnreadsToggle({
  surface,
}: {
  surface: ChannelsSurface;
}) {
  const switchId = useId();
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const setUnreadsOnly = useActivityFilterStore(
    (state) => state.setUnreadsOnly,
  );

  return (
    <div className="flex shrink-0 items-center gap-2">
      <Label htmlFor={switchId}>Unreads</Label>
      <Switch
        id={switchId}
        size="sm"
        checked={unreadsOnly}
        onCheckedChange={(next: boolean) => {
          setUnreadsOnly(next);
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "activity_unreads_toggle",
            surface,
            enabled: next,
          });
        }}
      />
    </div>
  );
}
