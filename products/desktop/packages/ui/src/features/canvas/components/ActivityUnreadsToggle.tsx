import { Label, Switch } from "@posthog/quill";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useId } from "react";

/** Narrows both Activity surfaces down to what hasn't been read yet. */
export function ActivityUnreadsToggle() {
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
        onCheckedChange={setUnreadsOnly}
      />
    </div>
  );
}
