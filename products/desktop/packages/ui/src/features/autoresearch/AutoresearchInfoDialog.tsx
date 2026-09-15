import {
  Command,
  EnvelopeSimple,
  Gauge,
  LockKey,
  Package,
  Question,
  Speedometer,
  TestTube,
} from "@phosphor-icons/react";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Text,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { domAnimation, LazyMotion, m, useReducedMotion } from "framer-motion";
import { useState } from "react";
import { openExternalUrl } from "../../shell/openExternal";
import { AutoresearchPromptRequirement } from "./AutoresearchPromptRequirement";

const AUTORESEARCH_FEEDBACK_MAILTO =
  "mailto:autoresearch@posthog.com?subject=PostHog%20Code%20Autoresearch%20feedback";

export function AutoresearchInfoDialog() {
  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button
            variant="link-muted"
            size="sm"
            aria-label="What is autoresearch?"
          />
        }
      >
        <Question />
        See how it works
      </DialogTrigger>
      <DialogContent size="wide">
        <DialogHeader>
          <DialogTitle>What is autoresearch?</DialogTitle>
          <DialogDescription>
            Autoresearch runs a bounded experiment loop inside this task.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1.35fr)_minmax(220px,1fr)]">
            <ExperimentLoopVisual />
            <div className="flex flex-col justify-center gap-3">
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

          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-(--radius-2) border border-border bg-gray-2 px-3 py-2">
            <Text size="xs" weight="medium" render={<li />}>
              Prompt requirements
            </Text>
            <AutoresearchPromptRequirement icon={Gauge} label="Metric" />
            <AutoresearchPromptRequirement icon={Command} label="Measurement" />
            <AutoresearchPromptRequirement icon={LockKey} label="Constraints" />
          </ul>

          <PromptExamples />

          <Text size="xs" variant="muted">
            Autoresearch does not invent or independently verify the metric. It
            follows the measurement instructions in your prompt.
          </Text>
        </div>

        <DialogFooter className="justify-between">
          <div className="flex items-center gap-2">
            <Button
              variant="link-muted"
              onClick={() => openExternalUrl(AUTORESEARCH_FEEDBACK_MAILTO)}
            >
              <EnvelopeSimple />
              Send feedback or report a bug
            </Button>
            <Text size="xs" variant="muted" className="hidden sm:inline">
              autoresearch@posthog.com
            </Text>
          </div>
          <DialogClose render={<Button variant="outline" />}>
            Got it
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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

function isPromptExampleKey(
  value: string | undefined,
): value is PromptExampleKey {
  return value !== undefined && value in PROMPT_EXAMPLES;
}

function PromptExamples() {
  const [selected, setSelected] = useState<PromptExampleKey>("performance");
  const example = PROMPT_EXAMPLES[selected];
  const ExampleIcon = example.icon;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Text size="sm" weight="medium">
          Example prompt
        </Text>
        <ToggleGroup
          aria-label="Example prompt"
          variant="outline"
          size="sm"
          value={[selected]}
          onValueChange={(next: string[]) => {
            if (isPromptExampleKey(next[0])) setSelected(next[0]);
          }}
        >
          {(Object.keys(PROMPT_EXAMPLES) as PromptExampleKey[]).map((key) => (
            <ToggleGroupItem key={key} value={key}>
              {PROMPT_EXAMPLES[key].title}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <div className="rounded-(--radius-2) border border-border px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <ExampleIcon size={13} className="text-muted-foreground" />
          <Text size="xs" weight="medium">
            {example.title}
          </Text>
        </div>
        <Text size="xs" variant="muted" className="mt-1 font-mono">
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
    <figure className="overflow-hidden rounded-(--radius-2) border border-border bg-gray-2">
      <div className="flex items-center justify-between border-border border-b px-3 py-2">
        <div>
          <Text size="xs" weight="medium">
            Example: reduce page load time
          </Text>
          <Text size="xs" variant="muted">
            Lower is better · 5 attempts
          </Text>
        </div>
        <div className="text-right">
          <Text size="xs" variant="muted">
            Best result
          </Text>
          <Text size="sm" weight="medium" className="text-green-11">
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

      <figcaption className="flex items-center gap-3 border-border border-t px-3 py-1.5 text-muted-foreground text-xs">
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-green-9" /> improved
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-orange-9" /> regressed
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
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-gray-4 font-medium text-gray-11 text-xs">
        {number}
      </span>
      <div>
        <Text size="sm" weight="medium">
          {title}
        </Text>
        <Text size="xs" variant="muted" className="mt-0.5">
          {description}
        </Text>
      </div>
    </div>
  );
}
