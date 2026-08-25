import { Gear } from "@phosphor-icons/react";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { BABYSIT_MODE_LABELS } from "@posthog/ui/features/settings/sections/BabysitSettings";
import {
  type BabysitMode,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

// The dot color per mode. "ask" carries the attention blue because it is the
// one mode that will prompt for a decision; the rest are status, not asks.
const MODE_DOT_COLOR: Record<BabysitMode, string> = {
  ask: "var(--blue-9)",
  auto: "var(--gray-9)",
  always: "var(--grass-9)",
  never: "var(--gray-7)",
};

const MODE_BLURB: Record<BabysitMode, string> = {
  ask: "When CI needs attention, the agent asks before it spends any turns fixing it.",
  auto: "The agent fixes failing checks and review comments on its own, up to 3 follow-up turns.",
  always:
    "The agent keeps watching the PR until it merges or closes, with no idle wait or turn cap.",
  never:
    "The agent does not watch the PR after opening it. No follow-up turns run.",
};

interface BabysitIndicatorProps {
  /** The task id, for analytics only. */
  taskId?: string;
}

/**
 * A small indicator near the composer that shows the current PR babysitting
 * mode and, on click, explains what the agent will do when CI needs attention.
 * The mode itself lives in the settings store; this is its read-out at the
 * point of use. The live "is this run being babysat right now" status is a
 * later round — this first round surfaces the user's choice.
 */
export function BabysitIndicator({ taskId }: BabysitIndicatorProps) {
  const babysitMode = useSettingsStore((s) => s.babysitMode);

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (open) {
        track(ANALYTICS_EVENTS.BABYSIT_INDICATOR_OPENED, {
          task_id: taskId,
          mode: babysitMode,
        });
      }
    },
    [taskId, babysitMode],
  );

  return (
    <Popover onOpenChange={handleOpenChange}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="icon-sm"
            aria-label={`PR babysitting: ${BABYSIT_MODE_LABELS[babysitMode]}`}
          >
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: MODE_DOT_COLOR[babysitMode] }}
              aria-hidden="true"
            />
          </Button>
        }
      />
      <PopoverContent
        side="top"
        align="end"
        sideOffset={6}
        className="w-[280px] gap-3"
      >
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: MODE_DOT_COLOR[babysitMode] }}
              aria-hidden="true"
            />
            <Text className="font-medium text-[13px]">
              PR babysitting: {BABYSIT_MODE_LABELS[babysitMode]}
            </Text>
          </div>
          <Text className="text-[12px] text-gray-11">
            {MODE_BLURB[babysitMode]}
          </Text>
        </div>
        <Button
          variant="link-muted"
          size="sm"
          className="self-start"
          onClick={() => {
            track(ANALYTICS_EVENTS.BABYSIT_INDICATOR_SETTINGS_OPENED, {
              task_id: taskId,
            });
            openSettings("general");
          }}
        >
          <Gear size={14} className="mr-1" />
          Change in settings
        </Button>
      </PopoverContent>
    </Popover>
  );
}
