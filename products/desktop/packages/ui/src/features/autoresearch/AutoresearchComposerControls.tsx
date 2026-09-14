import {
  ArrowDown,
  ArrowUp,
  ChartLineUp,
  Command,
  Gauge,
  LockKey,
  X,
} from "@phosphor-icons/react";
import type {
  AutoresearchDirection,
  AutoresearchDraftConfig,
} from "@posthog/core/autoresearch/schemas";
import {
  Button,
  NumberFieldDecrement,
  NumberFieldGroup,
  NumberFieldIncrement,
  NumberFieldInput,
  NumberFieldRoot,
  Text,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { domAnimation, LazyMotion, m, useReducedMotion } from "framer-motion";
import { AutoresearchAdvancedSettings } from "./AutoresearchAdvancedSettings";
import { AutoresearchInfoDialog } from "./AutoresearchInfoDialog";
import { AutoresearchPromptRequirement } from "./AutoresearchPromptRequirement";
import {
  type AutoresearchModelOption,
  clampMaxIterations,
} from "./stageModels";

interface AutoresearchComposerControlsProps {
  draft: AutoresearchDraftConfig;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  disabled?: boolean;
  onChange: (patch: Partial<AutoresearchDraftConfig>) => void;
  onExit: () => void;
}

const DIRECTIONS: readonly AutoresearchDirection[] = ["maximize", "minimize"];

/**
 * Compact autoresearch setup inside the new task composer. The prompt remains
 * the primary input; this row only exposes the two choices most people need.
 * Targets and per-stage model tuning stay behind advanced settings.
 */
export function AutoresearchComposerControls({
  draft,
  modelOptions,
  effortOptions,
  disabled = false,
  onChange,
  onExit,
}: AutoresearchComposerControlsProps) {
  return (
    <div className="flex w-full flex-col gap-3">
      <div className="flex items-start gap-2.5">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-(--radius-1) bg-gray-4 text-gray-11">
          <ChartLineUp size={13} weight="bold" />
        </span>
        <div className="min-w-0 flex-1">
          <Text size="sm" weight="medium">
            Autoresearch
          </Text>
          <Text size="xs" variant="muted">
            Iteratively modifies the codebase and evaluates a user defined
            metric.
          </Text>
        </div>
        <Button
          variant="link-muted"
          size="icon-sm"
          onClick={onExit}
          aria-label="Turn off autoresearch"
        >
          <X />
        </Button>
      </div>

      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 border-border border-t pt-3">
        <div className="flex flex-col gap-1.5">
          <Text size="xs" weight="medium" variant="muted">
            Goal
          </Text>
          <ToggleGroup
            aria-label="Metric goal"
            variant="outline"
            size="lg"
            value={[draft.direction]}
            disabled={disabled}
            onValueChange={(next: string[]) => {
              const direction = DIRECTIONS.find((item) => item === next[0]);
              if (direction) onChange({ direction });
            }}
          >
            {DIRECTIONS.map((direction) => (
              <ToggleGroupItem key={direction} value={direction}>
                <DirectionOption
                  direction={direction}
                  selected={draft.direction === direction}
                />
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>

        <div className="flex flex-col gap-1.5">
          <Text size="xs" weight="medium" variant="muted">
            Maximum attempts
          </Text>
          <NumberFieldRoot
            className="w-24"
            min={1}
            value={draft.maxIterations}
            onValueChange={(value) => {
              if (value === null) return;
              onChange({ maxIterations: clampMaxIterations(value) });
            }}
            disabled={disabled}
          >
            <NumberFieldGroup>
              <NumberFieldDecrement aria-label="Decrease attempts" />
              <NumberFieldInput
                id="autoresearch-attempts"
                aria-label="Maximum attempts"
              />
              <NumberFieldIncrement aria-label="Increase attempts" />
            </NumberFieldGroup>
          </NumberFieldRoot>
        </div>

        <div className="ml-auto">
          <AutoresearchAdvancedSettings
            draft={draft}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            disabled={disabled}
            onChange={onChange}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <Text size="xs" weight="medium" variant="muted">
            Include in your prompt
          </Text>
          <ul className="flex flex-col gap-1">
            <AutoresearchPromptRequirement
              icon={Gauge}
              label="The metric to optimize"
            />
            <AutoresearchPromptRequirement
              icon={Command}
              label="The command or steps to measure it"
            />
            <AutoresearchPromptRequirement
              icon={LockKey}
              label="Constraints the agent must preserve"
            />
          </ul>
        </div>
        <AutoresearchInfoDialog />
      </div>
    </div>
  );
}

function DirectionOption({
  direction,
  selected,
}: {
  direction: AutoresearchDirection;
  selected: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const DirectionIcon = direction === "maximize" ? ArrowUp : ArrowDown;
  const label = direction === "maximize" ? "Increase" : "Decrease";

  return (
    <span className="inline-flex items-center gap-1.5">
      <LazyMotion features={domAnimation}>
        <m.span
          className="inline-flex"
          animate={
            reducedMotion || !selected
              ? { y: 0 }
              : { y: direction === "maximize" ? [0, -2, 0] : [0, 2, 0] }
          }
          transition={{
            duration: 0.8,
            repeat: selected ? Number.POSITIVE_INFINITY : 0,
            repeatDelay: 1.4,
          }}
        >
          <DirectionIcon size={12} weight="bold" />
        </m.span>
      </LazyMotion>
      {label}
    </span>
  );
}
