import { CaretDown, Lightning, PiIcon, Stack } from "@phosphor-icons/react";
import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
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
import type { MessagingMode } from "@posthog/ui/features/sessions/messagingModeStore";
import { useRef, useState } from "react";

type PiModelOption = PiModelSelection & { name?: string };

interface PiModelSelectorProps {
  models: PiModelOption[];
  currentModel?: PiModelOption;
  thinkingLevel?: PiThinkingLevel;
  thinkingLevels?: PiThinkingLevel[];
  disabled?: boolean;
  onChange: (model: PiModelSelection) => void;
  onThinkingLevelChange?: (level: PiThinkingLevel) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
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
  onChange,
  onThinkingLevelChange,
  onHarnessChange,
}: PiModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const pendingChangeRef = useRef<(() => void) | null>(null);

  if (models.length === 0) {
    return null;
  }

  const currentValue = currentModel ? modelKey(currentModel) : "";
  const selectedModel =
    models.find((model) => modelKey(model) === currentValue) ?? currentModel;
  const currentLabel = modelLabel(selectedModel);
  const thinkingLabel = thinkingLevel
    ? (thinkingLevelLabels[thinkingLevel] ?? thinkingLevel)
    : undefined;

  const selectAndClose = (apply: () => void) => {
    pendingChangeRef.current = apply;
    setOpen(false);
  };

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen && pendingChangeRef.current !== null) {
          pendingChangeRef.current();
          pendingChangeRef.current = null;
        }
      }}
    >
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
            onChange={(harness) => {
              if (harness !== "pi") {
                selectAndClose(() => onHarnessChange(harness));
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
                  selectAndClose(() => onChange(model));
                }
              }}
            >
              {models.map((model) => (
                <DropdownMenuRadioItem
                  key={modelKey(model)}
                  value={modelKey(model)}
                >
                  <span className="whitespace-nowrap">{modelLabel(model)}</span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
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
                    selectAndClose(() =>
                      onThinkingLevelChange(value as PiThinkingLevel),
                    )
                  }
                >
                  {thinkingLevels.map((level) => (
                    <DropdownMenuRadioItem key={level} value={level}>
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
