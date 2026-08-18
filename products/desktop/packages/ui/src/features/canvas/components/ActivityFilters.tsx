import { Label, Switch } from "@posthog/quill";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useId } from "react";

function ActivityFilterToggle({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const switchId = useId();
  return (
    <div className="flex shrink-0 items-center gap-2">
      <Label htmlFor={switchId}>{label}</Label>
      <Switch
        id={switchId}
        size="sm"
        checked={checked}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

export function ActivityFilters() {
  const unreadsOnly = useActivityFilterStore((state) => state.unreadsOnly);
  const setUnreadsOnly = useActivityFilterStore(
    (state) => state.setUnreadsOnly,
  );
  const showMyActivity = useActivityFilterStore(
    (state) => state.showMyActivity,
  );
  const setShowMyActivity = useActivityFilterStore(
    (state) => state.setShowMyActivity,
  );

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <ActivityFilterToggle
        label="Unreads"
        checked={unreadsOnly}
        onCheckedChange={setUnreadsOnly}
      />
      <ActivityFilterToggle
        label="Show my activity"
        checked={showMyActivity}
        onCheckedChange={setShowMyActivity}
      />
    </div>
  );
}
