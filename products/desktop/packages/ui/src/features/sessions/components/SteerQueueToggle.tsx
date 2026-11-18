import { Lightning, Stack } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import {
  useMessagingMode,
  useSupportsNativeSteer,
} from "@posthog/ui/features/sessions/hooks/useMessagingMode";
import { useToggleMessagingMode } from "@posthog/ui/features/sessions/hooks/useToggleMessagingMode";
import { useQueuedMessagesForTask } from "@posthog/ui/features/sessions/useSession";

interface SteerQueueToggleProps {
  taskId: string;
}

export function steerQueueTooltip(
  isSteer: boolean,
  supportsNativeSteer: boolean,
  shortcut: string,
  queuedCount = 0,
): string {
  if (!isSteer) {
    // The button drops its "Queue" label in a narrow composer, so the count of
    // waiting messages has nowhere else to be read.
    const waiting =
      queuedCount > 0
        ? ` ${queuedCount} message${queuedCount === 1 ? "" : "s"} waiting.`
        : "";
    return `Queue: holds messages until the current turn ends.${waiting} ${shortcut} to switch to Steer.`;
  }
  return supportsNativeSteer
    ? `Steer: applies your message at the next safe boundary. The current command may keep running until then. ${shortcut} to switch to Queue.`
    : `Steer: interrupts the current turn and resends with your message. ${shortcut} to switch to Queue.`;
}

export function SteerQueueToggle({ taskId }: SteerQueueToggleProps) {
  const mode = useMessagingMode(taskId);
  const supportsNativeSteer = useSupportsNativeSteer(taskId);
  const queuedCount = useQueuedMessagesForTask(taskId).length;
  const toggle = useToggleMessagingMode(taskId);

  const isSteer = mode === "steer";
  const shortcut = formatHotkey(SHORTCUTS.SWITCH_MESSAGING_MODE);
  const label = isSteer
    ? "Steer"
    : queuedCount > 0
      ? `Queue (${queuedCount})`
      : "Queue";

  const tooltip = steerQueueTooltip(
    isSteer,
    supportsNativeSteer,
    shortcut,
    queuedCount,
  );

  const colorClass = isSteer ? "text-purple-11" : "text-muted-foreground";

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            aria-label={`Messaging mode: ${label}`}
            onClick={toggle}
          >
            <span className={colorClass}>
              {isSteer ? (
                <Lightning size={12} weight="fill" />
              ) : (
                <Stack size={12} />
              )}
            </span>
            {/* Both labels stack in one grid cell, so the button is always as
                wide as the longer of them. Sized by the label alone, toggling
                modes would shove the rest of the toolbar sideways. */}
            <span className="grid @max-[480px]/composer:hidden">
              <span aria-hidden className="invisible col-start-1 row-start-1">
                Steer
              </span>
              <span aria-hidden className="invisible col-start-1 row-start-1">
                Queue
              </span>
              <span className={cn("col-start-1 row-start-1", colorClass)}>
                {label}
              </span>
            </span>
            {/* The icon still names the mode once the label is gone, but the
                number of waiting messages has no other place on the row. */}
            {queuedCount > 0 && (
              <span
                className={cn(
                  "@max-[480px]/composer:inline hidden",
                  colorClass,
                )}
              >
                {queuedCount}
              </span>
            )}
          </Button>
        }
      />
      <TooltipContent side="top">{tooltip}</TooltipContent>
    </Tooltip>
  );
}
