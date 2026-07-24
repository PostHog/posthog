import {
  ArrowDown,
  ArrowUp,
  ChartLineUp,
  Command,
  EnvelopeSimple,
  Gauge,
  LockKey,
  Package,
  Question,
  SlidersHorizontal,
  Speedometer,
  TestTube,
  X,
} from "@phosphor-icons/react";
import type {
  AutoresearchDirection,
  AutoresearchDraftConfig,
} from "@posthog/core/autoresearch/schemas";
import {
  Button,
  Dialog,
  Popover,
  SegmentedControl,
  Text,
  TextField,
} from "@radix-ui/themes";
import { domAnimation, LazyMotion, m, useReducedMotion } from "framer-motion";
import { useState } from "react";
import { openExternalUrl } from "../../shell/openExternal";
import {
  type AutoresearchModelOption,
  clampMaxIterations,
  StageModelSelect,
  stageValueLabel,
} from "./stageModels";

interface AutoresearchComposerControlsProps {
  draft: AutoresearchDraftConfig;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  disabled?: boolean;
  onChange: (patch: Partial<AutoresearchDraftConfig>) => void;
  onExit: () => void;
}

const AUTORESEARCH_FEEDBACK_MAILTO =
  "mailto:autoresearch@posthog.com?subject=PostHog%20Code%20Autoresearch%20feedback";

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
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-gray-4 text-gray-11">
          <ChartLineUp size={13} weight="bold" />
        </div>
        <div className="min-w-0 flex-1">
          <Text size="2" weight="medium">
            Autoresearch
          </Text>
          <Text as="p" size="1" color="gray" className="mt-0.5 leading-4">
            Iteratively modifies the codebase and evaluates a user defined
            metric.
          </Text>
        </div>
        <button
          type="button"
          onClick={onExit}
          aria-label="Turn off autoresearch"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-10 hover:bg-gray-4 hover:text-gray-12"
        >
          <X size={13} />
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 border-gray-5 border-t pt-3">
        <div>
          <Text
            as="label"
            htmlFor="autoresearch-direction"
            size="1"
            weight="medium"
            className="mb-1.5 block text-gray-11"
          >
            Goal
          </Text>
          <SegmentedControl.Root
            size="1"
            value={draft.direction}
            onValueChange={(value) =>
              onChange({ direction: value as AutoresearchDirection })
            }
            disabled={disabled}
            aria-label="Metric goal"
          >
            <SegmentedControl.Item value="maximize">
              <DirectionOption
                direction="maximize"
                selected={draft.direction === "maximize"}
              />
            </SegmentedControl.Item>
            <SegmentedControl.Item value="minimize">
              <DirectionOption
                direction="minimize"
                selected={draft.direction === "minimize"}
              />
            </SegmentedControl.Item>
          </SegmentedControl.Root>
        </div>

        <div>
          <Text
            as="label"
            htmlFor="autoresearch-attempts"
            size="1"
            weight="medium"
            className="mb-1.5 block text-gray-11"
          >
            Maximum attempts
          </Text>
          <div className="flex items-center gap-1.5">
            <TextField.Root
              size="1"
              id="autoresearch-attempts"
              className="w-16"
              value={String(draft.maxIterations)}
              onChange={(event) =>
                onChange({
                  maxIterations: clampMaxIterations(
                    Number.parseInt(event.target.value, 10),
                  ),
                })
              }
              inputMode="numeric"
              aria-label="Maximum attempts"
              disabled={disabled}
            />
          </div>
        </div>

        <div className="ml-auto">
          <AdvancedSettings
            draft={draft}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            disabled={disabled}
            onChange={onChange}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3 pt-0.5">
        <div>
          <Text as="div" size="1" weight="medium" color="gray">
            Include in your prompt
          </Text>
          <ul className="mt-1.5 flex flex-col gap-1">
            <PromptRequirement icon={Gauge} label="The metric to optimize" />
            <PromptRequirement
              icon={Command}
              label="The command or steps to measure it"
            />
            <PromptRequirement
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

function PromptRequirement({
  icon: Icon,
  label,
}: {
  icon: typeof Gauge;
  label: string;
}) {
  return (
    <li className="flex items-center gap-1.5 text-gray-10 text-xs">
      <Icon size={13} className="shrink-0" />
      <span>{label}</span>
    </li>
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
  const Icon = direction === "maximize" ? ArrowUp : ArrowDown;
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
          <Icon size={12} weight="bold" />
        </m.span>
      </LazyMotion>
      {label}
    </span>
  );
}

function AutoresearchInfoDialog() {
  return (
    <Dialog.Root>
      <Dialog.Trigger>
        <Button
          size="1"
          variant="ghost"
          color="gray"
          aria-label="What is autoresearch?"
          className="text-gray-10"
        >
          <Question size={13} />
          See how it works
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="720px" size="2">
        <Dialog.Title className="text-base">What is autoresearch?</Dialog.Title>
        <Dialog.Description className="text-sm" color="gray">
          Autoresearch runs a bounded experiment loop inside this task.
        </Dialog.Description>

        <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1.35fr)_minmax(220px,1fr)]">
          <ExperimentLoopVisual />
          <div className="flex flex-col justify-center gap-3 text-sm">
            <InfoRow
              number="1"
              title="Measure a baseline"
              description="Run the measurement from your prompt."
            />
            <InfoRow
              number="2"
              title="Try an improvement"
              description="Change the code and measure again."
            />
            <InfoRow
              number="3"
              title="Repeat until it stops"
              description="Stop at the attempt limit or target value."
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md border border-gray-5 bg-gray-2 px-3 py-2">
          <Text size="1" weight="medium">
            Prompt requirements
          </Text>
          <PromptRequirement icon={Gauge} label="Metric" />
          <PromptRequirement icon={Command} label="Measurement" />
          <PromptRequirement icon={LockKey} label="Constraints" />
        </div>

        <PromptExamples />

        <Text as="p" size="1" color="gray" className="mt-2 leading-4">
          Autoresearch does not invent or independently verify the metric. It
          follows the measurement instructions in your prompt.
        </Text>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-gray-5 border-t pt-3">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              color="gray"
              onClick={() => openExternalUrl(AUTORESEARCH_FEEDBACK_MAILTO)}
            >
              <EnvelopeSimple size={14} />
              Send feedback or report a bug
            </Button>
            <Text size="1" color="gray" className="hidden sm:inline">
              autoresearch@posthog.com
            </Text>
          </div>
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Got it
            </Button>
          </Dialog.Close>
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}

const PROMPT_EXAMPLES = {
  performance: {
    icon: Speedometer,
    title: "Performance",
    prompt:
      "Reduce the p95 response time of the search endpoint. Measure with `pnpm bench:search` and minimize the reported p95 milliseconds. Preserve response behavior and API compatibility.",
  },
  bundle: {
    icon: Package,
    title: "Bundle size",
    prompt:
      "Reduce the gzipped JavaScript bundle size reported by `pnpm build:analyze`. Minimize total kB without removing features or changing browser support.",
  },
  reliability: {
    icon: TestTube,
    title: "Test reliability",
    prompt:
      "Reduce failures in the checkout E2E suite. Measure by running `pnpm test:e2e checkout --repeat-each=20` and minimize failed runs without increasing test timeouts.",
  },
} as const;

type PromptExampleKey = keyof typeof PROMPT_EXAMPLES;

function PromptExamples() {
  const [selected, setSelected] = useState<PromptExampleKey>("performance");
  const example = PROMPT_EXAMPLES[selected];
  const Icon = example.icon;

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Text as="div" size="2" weight="medium">
          Example prompt
        </Text>
        <SegmentedControl.Root
          size="1"
          value={selected}
          onValueChange={(value) => {
            if (value in PROMPT_EXAMPLES)
              setSelected(value as PromptExampleKey);
          }}
          aria-label="Example prompt"
        >
          {Object.entries(PROMPT_EXAMPLES).map(([key, item]) => (
            <SegmentedControl.Item key={key} value={key}>
              {item.title}
            </SegmentedControl.Item>
          ))}
        </SegmentedControl.Root>
      </div>
      <div className="mt-2 rounded-md border border-gray-5 px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <Icon size={13} className="text-gray-10" />
          <Text size="1" weight="medium">
            {example.title}
          </Text>
        </div>
        <Text as="p" size="1" color="gray" className="mt-1 font-mono leading-4">
          {example.prompt}
        </Text>
      </div>
    </div>
  );
}

const EXPERIMENT_POINTS = [
  { x: 38, y: 91, value: 72, label: "Baseline", improved: true },
  { x: 106, y: 70, value: 66, label: "Attempt 1", improved: true },
  { x: 174, y: 79, value: 69, label: "Attempt 2", improved: false },
  { x: 242, y: 45, value: 60, label: "Attempt 3", improved: true },
  { x: 310, y: 27, value: 55, label: "Best", improved: true },
] as const;

function ExperimentLoopVisual() {
  const reducedMotion = useReducedMotion();
  const path = EXPERIMENT_POINTS.map(
    (point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`,
  ).join(" ");

  return (
    <figure className="overflow-hidden rounded-md border border-gray-5 bg-gray-2">
      <div className="flex items-center justify-between border-gray-5 border-b px-3 py-2">
        <div>
          <Text as="div" size="1" weight="medium">
            Example: reduce page load time
          </Text>
          <Text as="div" size="1" color="gray">
            Lower is better · 5 attempts
          </Text>
        </div>
        <div className="text-right">
          <Text as="div" size="1" color="gray">
            Best result
          </Text>
          <Text as="div" size="2" weight="medium" className="text-green-11">
            55 ms
          </Text>
        </div>
      </div>

      <svg
        viewBox="0 0 348 132"
        className="block h-32 w-full"
        role="img"
        aria-labelledby="autoresearch-chart-title autoresearch-chart-description"
      >
        <title id="autoresearch-chart-title">
          Example autoresearch metric improving over five attempts
        </title>
        <desc id="autoresearch-chart-description">
          Page load time starts at 72 milliseconds, briefly regresses, and
          reaches a best result of 55 milliseconds.
        </desc>

        {[30, 60, 90].map((y) => (
          <line
            key={y}
            x1="28"
            x2="322"
            y1={y}
            y2={y}
            stroke="var(--gray-5)"
            strokeWidth="1"
          />
        ))}

        <LazyMotion features={domAnimation}>
          <m.path
            d={path}
            fill="none"
            stroke="var(--gray-10)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reducedMotion ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.1, ease: "easeOut" }}
          />

          {EXPERIMENT_POINTS.map((point, index) => (
            <m.g
              key={point.label}
              initial={
                reducedMotion ? false : { opacity: 0, scale: 0.65, y: 4 }
              }
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ delay: 0.18 + index * 0.18, duration: 0.25 }}
              style={{ transformOrigin: `${point.x}px ${point.y}px` }}
            >
              <circle
                cx={point.x}
                cy={point.y}
                r={index === EXPERIMENT_POINTS.length - 1 ? 5 : 4}
                fill={point.improved ? "var(--green-9)" : "var(--orange-9)"}
                stroke="var(--gray-2)"
                strokeWidth="2"
              />
              <text
                x={point.x}
                y={point.y - 10}
                textAnchor="middle"
                fill="var(--gray-12)"
                fontSize="10"
                fontWeight="500"
              >
                {point.value}
              </text>
              <text
                x={point.x}
                y="119"
                textAnchor="middle"
                fill="var(--gray-10)"
                fontSize="9"
              >
                {index === 0 ? "Baseline" : index}
              </text>
            </m.g>
          ))}
        </LazyMotion>
      </svg>

      <figcaption className="flex items-center gap-3 border-gray-5 border-t px-3 py-1.5 text-gray-10 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-green-9" /> improved
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-orange-9" /> regressed
        </span>
      </figcaption>
    </figure>
  );
}

function InfoRow({
  number,
  title,
  description,
}: {
  number: string;
  title: string;
  description: string;
}) {
  return (
    <div className="flex gap-3">
      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-4 font-medium text-gray-11 text-xs">
        {number}
      </div>
      <div>
        <Text as="div" size="2" weight="medium">
          {title}
        </Text>
        <Text as="p" size="1" color="gray" className="mt-0.5 leading-4">
          {description}
        </Text>
      </div>
    </div>
  );
}

function stageSummary(
  model: string | null,
  effort: string | null,
  modelOptions: AutoresearchModelOption[],
  effortOptions: AutoresearchModelOption[],
): string {
  const modelLabel = stageValueLabel(model, modelOptions) ?? "task model";
  const effortLabel = stageValueLabel(effort, effortOptions);
  return effortLabel ? `${modelLabel} · ${effortLabel}` : modelLabel;
}

function AdvancedSettings({
  draft,
  modelOptions,
  effortOptions,
  disabled,
  onChange,
}: {
  draft: AutoresearchDraftConfig;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  disabled: boolean;
  onChange: (patch: Partial<AutoresearchDraftConfig>) => void;
}) {
  const split =
    draft.implementModel !== draft.measureModel ||
    draft.implementEffort !== draft.measureEffort;
  const hasTarget = draft.targetValue !== null;

  return (
    <Popover.Root>
      <Popover.Trigger>
        <Button
          size="1"
          variant="ghost"
          color="gray"
          disabled={disabled}
          aria-label="Advanced autoresearch settings"
        >
          <SlidersHorizontal size={14} />
          Advanced
          {(split || hasTarget) && <span aria-hidden>•</span>}
        </Button>
      </Popover.Trigger>
      <Popover.Content size="2" width="360px">
        <div className="flex flex-col gap-4">
          <div>
            <Text as="div" size="2" weight="medium">
              Advanced settings
            </Text>
            <Text as="p" size="1" color="gray" className="mt-0.5">
              Optional stopping and model controls.
            </Text>
          </div>

          <div>
            <Text
              as="label"
              htmlFor="autoresearch-target"
              size="1"
              weight="medium"
              className="mb-1 block"
            >
              Stop early at this metric value
            </Text>
            <TextField.Root
              size="2"
              id="autoresearch-target"
              value={
                draft.targetValue === null ? "" : String(draft.targetValue)
              }
              onChange={(event) => {
                const raw = event.target.value.trim();
                const numeric = Number(raw);
                onChange({
                  targetValue:
                    raw === "" || !Number.isFinite(numeric) ? null : numeric,
                });
              }}
              placeholder="Optional"
              inputMode="decimal"
              aria-label="Target metric value to stop at"
              disabled={disabled}
            />
          </div>

          <StageFields
            legend="Build improvements"
            description="Used to analyze the result and change the code."
            model={draft.implementModel}
            effort={draft.implementEffort}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            onModelChange={(value) => onChange({ implementModel: value })}
            onEffortChange={(value) => onChange({ implementEffort: value })}
          />
          <StageFields
            legend="Measure results"
            description="Used to run the measurement without changing code."
            model={draft.measureModel}
            effort={draft.measureEffort}
            modelOptions={modelOptions}
            effortOptions={effortOptions}
            onModelChange={(value) => onChange({ measureModel: value })}
            onEffortChange={(value) => onChange({ measureEffort: value })}
          />

          {split && (
            <Text size="1" color="gray">
              Build:{" "}
              {stageSummary(
                draft.implementModel,
                draft.implementEffort,
                modelOptions,
                effortOptions,
              )}
              . Measure:{" "}
              {stageSummary(
                draft.measureModel,
                draft.measureEffort,
                modelOptions,
                effortOptions,
              )}
              .
            </Text>
          )}
        </div>
      </Popover.Content>
    </Popover.Root>
  );
}

function StageFields({
  legend,
  description,
  model,
  effort,
  modelOptions,
  effortOptions,
  onModelChange,
  onEffortChange,
}: {
  legend: string;
  description: string;
  model: string | null;
  effort: string | null;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  onModelChange: (value: string | null) => void;
  onEffortChange: (value: string | null) => void;
}) {
  return (
    <div>
      <Text as="div" size="1" weight="medium">
        {legend}
      </Text>
      <Text as="div" size="1" color="gray" className="mb-1.5">
        {description}
      </Text>
      <div className="flex gap-2">
        <StageModelSelect
          className="flex-1"
          ariaLabel={`${legend} model`}
          noneLabel="Task model"
          value={model}
          options={modelOptions}
          onChange={onModelChange}
        />
        {effortOptions.length > 0 && (
          <StageModelSelect
            className="w-28"
            ariaLabel={`${legend} effort`}
            noneLabel="Default effort"
            value={effort}
            options={effortOptions}
            onChange={onEffortChange}
          />
        )}
      </div>
    </div>
  );
}
