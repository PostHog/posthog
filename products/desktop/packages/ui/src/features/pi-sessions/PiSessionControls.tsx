import { CaretDown, Lightning, Stack } from "@phosphor-icons/react";
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import { ReasoningLevelDropdown } from "@posthog/ui/features/sessions/components/ReasoningLevelDropdown";
import type { MessagingMode } from "@posthog/ui/features/sessions/messagingModeStore";
import { Fragment } from "react";

interface PiModelSelectorProps {
  models: PiModelSelection[];
  currentModel?: PiModelSelection;
  disabled?: boolean;
  onChange: (model: PiModelSelection) => void;
}

function modelKey(model: PiModelSelection): string {
  return JSON.stringify([model.provider, model.id]);
}

export function PiModelSelector({
  models,
  currentModel,
  disabled,
  onChange,
}: PiModelSelectorProps) {
  if (models.length === 0) {
    return null;
  }

  const modelsByProvider = new Map<string, PiModelSelection[]>();
  for (const model of models) {
    const providerModels = modelsByProvider.get(model.provider) ?? [];
    providerModels.push(model);
    modelsByProvider.set(model.provider, providerModels);
  }

  const currentValue = currentModel ? modelKey(currentModel) : "";
  const currentLabel = currentModel?.id ?? "Model";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label="Model"
          >
            {currentLabel}
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
        className="min-w-[220px]"
      >
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
          {[...modelsByProvider.entries()].map(
            ([provider, providerModels], index) => (
              <Fragment key={provider}>
                {index > 0 && <DropdownMenuSeparator />}
                <MenuLabel>{provider}</MenuLabel>
                {providerModels.map((model) => (
                  <DropdownMenuRadioItem
                    key={modelKey(model)}
                    value={modelKey(model)}
                  >
                    <span className="whitespace-nowrap">{model.id}</span>
                  </DropdownMenuRadioItem>
                ))}
              </Fragment>
            ),
          )}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
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

interface PiThinkingLevelSelectorProps {
  level: PiThinkingLevel;
  levels: PiThinkingLevel[];
  disabled?: boolean;
  onChange: (level: PiThinkingLevel) => void;
}

export function PiThinkingLevelSelector({
  level,
  levels,
  disabled,
  onChange,
}: PiThinkingLevelSelectorProps) {
  return (
    <ReasoningLevelDropdown
      value={level}
      options={levels.map((value) => ({
        value,
        label: thinkingLevelLabels[value] ?? value,
      }))}
      onChange={(value) => onChange(value as PiThinkingLevel)}
      variant="slider"
      label="Thinking"
      disabled={disabled}
    />
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
