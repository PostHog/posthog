import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { Brain, CaretDown } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import type { Adapter } from "@posthog/shared";
import { useRef, useState } from "react";
import { flattenSelectOptions } from "../sessionStore";
import { useRetainedConfigOption } from "../useRetainedConfigOption";

interface ReasoningLevelSelectorProps {
  thoughtOption?: SessionConfigOption;
  adapter?: Adapter;
  onChange?: (value: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
}

export function ReasoningLevelSelector({
  thoughtOption,
  adapter,
  onChange,
  disabled,
  isLoading,
}: ReasoningLevelSelectorProps) {
  const [open, setOpen] = useState(false);
  const pendingValueRef = useRef<string | null>(null);
  const displayOption = useRetainedConfigOption(thoughtOption);

  // Genuinely no reasoning levels for this harness/model: hide. While the
  // preview config reloads (a harness switch) keep showing the last value,
  // disabled, so the toolbar doesn't collapse mid-switch.
  if (!thoughtOption && !isLoading) return null;
  if (!displayOption || displayOption.type !== "select") {
    return null;
  }

  const isReloading = !thoughtOption;
  const isDisabled = disabled || isReloading;

  const options = flattenSelectOptions(displayOption.options);
  if (options.length === 0) return null;
  const activeLevel = displayOption.currentValue;
  const activeLabel =
    options.find((opt) => opt.value === activeLevel)?.name ?? activeLevel;
  const prefix = adapter === "codex" ? "Reasoning" : "Effort";

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen && pendingValueRef.current !== null) {
          onChange?.(pendingValueRef.current);
          pendingValueRef.current = null;
        }
      }}
    >
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={isDisabled}
            aria-label={`${prefix}: ${activeLabel}`}
          >
            <Brain size={14} className="text-muted-foreground" />
            {activeLabel}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[180px]"
      >
        <MenuLabel>{adapter === "codex" ? "Reasoning" : "Effort"}</MenuLabel>
        <DropdownMenuRadioGroup
          value={activeLevel}
          onValueChange={(value) => {
            pendingValueRef.current = value;
            setOpen(false);
          }}
        >
          {options.map((level) => (
            <DropdownMenuRadioItem key={level.value} value={level.value}>
              <span className="whitespace-nowrap">{level.name}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
