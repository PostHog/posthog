import { CaretDown, Lightning, Stack } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import type { MessagingMode } from "@posthog/ui/features/sessions/messagingModeStore";

interface PiMessagingModeSelectorProps {
  mode: MessagingMode;
  queuedCount: number;
  disabled?: boolean;
  onModeChange: (mode: MessagingMode) => void;
}

export function PiMessagingModeSelector({
  mode,
  queuedCount,
  disabled,
  onModeChange,
}: PiMessagingModeSelectorProps) {
  let label = "Queue";
  if (mode === "steer") {
    label = "Steer";
  } else if (queuedCount > 0) {
    label = `Queue (${queuedCount})`;
  }

  const colorClass = mode === "steer" ? "text-purple-11" : "text-gray-11";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label={`Messaging mode: ${label}`}
          >
            <span className={colorClass}>
              {mode === "steer" ? (
                <Lightning size={12} weight="fill" />
              ) : (
                <Stack size={12} />
              )}
            </span>
            <span className={colorClass}>{label}</span>
            <CaretDown size={10} weight="bold" className={colorClass} />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[240px]"
      >
        <MenuLabel>While Pi is generating</MenuLabel>
        <DropdownMenuRadioGroup
          value={mode}
          onValueChange={(value) => onModeChange(value as MessagingMode)}
        >
          <DropdownMenuRadioItem value="steer">
            Steer at the next tool boundary
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="queue">
            Queue for the next turn
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
