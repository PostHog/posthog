import {
  CaretDown,
  Lightning,
  PiIcon,
  Spinner,
  Stack,
} from "@phosphor-icons/react";
import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import {
  type AgentHarness,
  HarnessSubmenu,
} from "@posthog/ui/features/sessions/components/HarnessSubmenu";
import {
  ModelCostChip,
  ModelCostFooter,
} from "@posthog/ui/features/sessions/components/ModelCostChip";
import type { MessagingMode } from "@posthog/ui/features/sessions/messagingModeStore";
import { useState } from "react";

type PiModelOption = PiModelSelection & { name?: string };

interface PiModelSelectorProps {
  models: PiModelOption[];
  currentModel?: PiModelOption;
  thinkingLevel?: PiThinkingLevel;
  thinkingLevels?: PiThinkingLevel[];
  disabled?: boolean;
  isLoading?: boolean;
  onChange: (model: PiModelSelection) => void;
  onThinkingLevelChange?: (level: PiThinkingLevel) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
}

function modelKey(model: PiModelSelection): string {
  return JSON.stringify([model.provider, model.id]);
}

function modelLabel(model?: PiModelOption): string {
  return model?.name ?? model?.id ?? "Model";
}

const thinkingLevelLabels: Record<PiThinkingLevel, string> = {
  off: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra High",
  max: "Max",
};

export function PiModelSelector({
  models,
  currentModel,
  thinkingLevel,
  thinkingLevels = [],
  disabled,
  isLoading,
  onChange,
  onThinkingLevelChange,
  onHarnessChange,
  menuOpen,
  onMenuOpenChange,
}: PiModelSelectorProps) {
  const [internalMenuOpen, setInternalMenuOpen] = useState(false);
  const open = menuOpen ?? internalMenuOpen;
  const setOpen = onMenuOpenChange ?? setInternalMenuOpen;

  if (models.length === 0) {
    if (isLoading) {
      // Keep the dropdown mounted while the Pi catalog first loads (a
      // harness switch to Pi): unmounting it closes a menu the user is
      // mid-interaction with.
      return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="default" size="sm">
                <span className="text-muted-foreground">
                  <PiIcon size={14} weight="bold" className="translate-y-px" />
                </span>
                <Spinner size={12} className="animate-spin" />
                Loading...
              </Button>
            }
          />
          <DropdownMenuContent
            align="start"
            side="top"
            sideOffset={6}
            className="min-w-[230px]"
          >
            {onHarnessChange && (
              <HarnessSubmenu
                value="pi"
                includePi
                closeOnChange={false}
                onChange={(harness) => {
                  if (harness !== "pi") {
                    onHarnessChange(harness);
                  }
                }}
              />
            )}
            <DropdownMenuItem disabled>
              <Spinner size={12} className="animate-spin" />
              Loading models...
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      );
    }
    return null;
  }

  const currentValue = currentModel ? modelKey(currentModel) : "";
  const selectedModel =
    models.find((model) => modelKey(model) === currentValue) ?? currentModel;
  const currentLabel = modelLabel(selectedModel);
  const thinkingLabel = thinkingLevel
    ? (thinkingLevelLabels[thinkingLevel] ?? thinkingLevel)
    : undefined;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label={
              thinkingLabel
                ? `Model and reasoning: ${currentLabel} ${thinkingLabel}`
                : `Model: ${currentLabel}`
            }
          >
            <span className="text-muted-foreground">
              <PiIcon size={14} weight="bold" className="translate-y-px" />
            </span>
            <span className="font-medium text-foreground">{currentLabel}</span>
            {thinkingLabel && (
              <span className="font-normal text-muted-foreground/80">
                {thinkingLabel}
              </span>
            )}
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
        className="min-w-[230px]"
      >
        {onHarnessChange && (
          <HarnessSubmenu
            value="pi"
            includePi
            closeOnChange={false}
            onChange={(harness) => {
              if (harness !== "pi") {
                onHarnessChange(harness);
              }
            }}
          />
        )}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <span>Model</span>
            <span className="flex-1 text-right text-muted-foreground">
              {currentLabel}
            </span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="min-w-[220px]">
            <DropdownMenuRadioGroup
              value={currentValue}
              onValueChange={(value) => {
                const model = models.find(
                  (candidate) => modelKey(candidate) === value,
                );
                if (model) {
                  onChange(model);
                }
              }}
            >
              {models.map((model) => (
                <DropdownMenuRadioItem
                  key={modelKey(model)}
                  value={modelKey(model)}
                  closeOnClick={false}
                >
                  <span className="whitespace-nowrap">{modelLabel(model)}</span>
                  <ModelCostChip modelId={model.id} />
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <ModelCostFooter />
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        {thinkingLevel &&
          onThinkingLevelChange &&
          thinkingLevels.length > 0 && (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <span>Reasoning</span>
                <span className="flex-1 text-right text-muted-foreground">
                  {thinkingLabel}
                </span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuRadioGroup
                  value={thinkingLevel}
                  onValueChange={(value) =>
                    onThinkingLevelChange(value as PiThinkingLevel)
                  }
                >
                  {thinkingLevels.map((level) => (
                    <DropdownMenuRadioItem
                      key={level}
                      value={level}
                      closeOnClick={false}
                    >
                      {thinkingLevelLabels[level] ?? level}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

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
            Steer after the current tool finishes
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="queue">
            Queue for the next turn
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
