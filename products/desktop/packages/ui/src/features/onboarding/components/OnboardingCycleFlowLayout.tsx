import "./OnboardingCycleFlowLayout.css";
import {
  ArrowRightIcon,
  ArrowsClockwiseIcon,
  ChartLineUpIcon,
  CheckCircleIcon,
  CircleNotchIcon,
  FileCodeIcon,
  FileTextIcon,
  PaperPlaneRightIcon,
  PauseIcon,
  PlayIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { Badge, Button, cn } from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { type ReactNode, useEffect, useRef, useState } from "react";

const CYCLE_DURATION_MS = 5_000;

type CyclePreviewKind =
  | "user-input"
  | "self-driving"
  | "loops"
  | "autoresearch"
  | "build-task"
  | "investigate"
  | "scheduled-run"
  | "experiment"
  | "code-change"
  | "report"
  | "canvas";

interface CycleAction {
  destination: OnboardingLandingDestination;
  href: string;
  label: string;
}

interface CycleStage {
  label: "Input" | "Agent work" | "Result";
  title: string;
  description: string;
  preview: CyclePreviewKind;
  badge?: string;
  action?: CycleAction;
}

interface CyclePath {
  name: string;
  input: CycleStage;
  agent: CycleStage;
  result: CycleStage;
}

interface OnboardingCycleFlowLayoutProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

const cyclePaths: CyclePath[] = [
  {
    name: "Task to code change",
    input: {
      label: "Input",
      title: "User input",
      description:
        "Describe a change in a task. Add context before you send it to an agent.",
      preview: "user-input",
      action: {
        destination: "tasks",
        href: "/new",
        label: "Create a task",
      },
    },
    agent: {
      label: "Agent work",
      title: "Build the task",
      description:
        "The agent reads the task, edits the code, and runs checks. Add guidance in the thread.",
      preview: "build-task",
      action: {
        destination: "agents",
        href: "/agents",
        label: "Open agents",
      },
    },
    result: {
      label: "Result",
      title: "Code change",
      description:
        "Review the changed files, checks, and implementation notes before you merge.",
      preview: "code-change",
    },
  },
  {
    name: "Signal to report",
    input: {
      label: "Input",
      title: "Self-driving",
      description:
        "Choose a prioritized finding that Desktop created from activity in your project.",
      preview: "self-driving",
      action: {
        destination: "self-driving",
        href: "/inbox",
        label: "Open self-driving",
      },
    },
    agent: {
      label: "Agent work",
      title: "Investigate the signal",
      description:
        "The agent checks the activity behind the finding and collects evidence for review.",
      preview: "investigate",
      action: {
        destination: "agents",
        href: "/agents",
        label: "Open agents",
      },
    },
    result: {
      label: "Result",
      title: "Report",
      description:
        "Read a summary of the finding, its likely cause, and the supporting evidence.",
      preview: "report",
      action: {
        destination: "self-driving",
        href: "/inbox",
        label: "Open self-driving",
      },
    },
  },
  {
    name: "Loop to report",
    input: {
      label: "Input",
      title: "Loops",
      description:
        "Run the same saved task on a schedule with the latest context.",
      preview: "loops",
      badge: "Coming soon",
    },
    agent: {
      label: "Agent work",
      title: "Run the saved task",
      description:
        "The agent follows the same instructions again and records what changed since the last run.",
      preview: "scheduled-run",
      action: {
        destination: "agents",
        href: "/agents",
        label: "Open agents",
      },
    },
    result: {
      label: "Result",
      title: "Report",
      description:
        "Review a new summary for each run and compare it with earlier results.",
      preview: "report",
    },
  },
  {
    name: "Metric to canvas",
    input: {
      label: "Input",
      title: "Autoresearch",
      description:
        "Choose a metric and give the agent a change that it can test repeatedly.",
      preview: "autoresearch",
    },
    agent: {
      label: "Agent work",
      title: "Test and measure",
      description:
        "The agent changes one variable, measures the metric, and keeps the best result.",
      preview: "experiment",
      action: {
        destination: "agents",
        href: "/agents",
        label: "Open agents",
      },
    },
    result: {
      label: "Result",
      title: "Canvas",
      description:
        "Keep the measurements and conclusions in a shared document or data view.",
      preview: "canvas",
      action: {
        destination: "canvases",
        href: "/canvases",
        label: "Open canvases",
      },
    },
  },
];

function renderPreview(kind: CyclePreviewKind): ReactNode {
  switch (kind) {
    case "user-input":
      return (
        <div className="w-full max-w-52 rounded-(--radius-3) border border-border bg-gray-1 p-3 shadow-sm">
          <div className="mb-5 h-2 w-4/5 rounded-full bg-gray-7" />
          <div className="h-2 w-1/2 rounded-full bg-gray-5" />
          <div className="mt-4 flex items-center border-border border-t pt-3">
            <span className="h-1.5 w-14 rounded-full bg-gray-6" />
            <span className="ml-auto flex size-7 items-center justify-center rounded-(--radius-2) bg-(--accent-9) text-white">
              <PaperPlaneRightIcon size={13} weight="fill" />
            </span>
          </div>
        </div>
      );
    case "self-driving":
      return (
        <div className="w-full max-w-56 overflow-hidden rounded-(--radius-3) border border-border bg-gray-1 shadow-sm">
          <div className="flex items-center justify-between border-border border-b px-3 py-2 text-[10px]">
            <span className="flex items-center gap-1.5 font-medium">
              <TrayIcon size={12} /> Inbox
            </span>
            <span className="rounded-full bg-blue-3 px-1.5 py-0.5 text-blue-11">
              2 ready
            </span>
          </div>
          <div className="divide-y divide-border px-3">
            {[
              ["P1", "Checkout drop-off", "bg-orange-3 text-orange-11"],
              ["P2", "Payment errors", "bg-yellow-3 text-yellow-11"],
              ["P2", "Invite failures", "bg-yellow-3 text-yellow-11"],
            ].map(([priority, title, tone]) => (
              <div key={title} className="flex items-center gap-2 py-2.5">
                <span
                  className={cn(
                    "rounded px-1 py-0.5 font-semibold text-[8px]",
                    tone,
                  )}
                >
                  {priority}
                </span>
                <span className="font-medium text-[9px]">{title}</span>
              </div>
            ))}
          </div>
        </div>
      );
    case "loops":
      return (
        <div className="relative size-36">
          <svg viewBox="0 0 144 144" className="size-full text-blue-9">
            <title>Scheduled work loop</title>
            <path
              d="M40 26H104Q122 26 122 44V100Q122 118 104 118H40Q22 118 22 100V44Q22 26 40 26Z"
              fill="none"
              stroke="currentColor"
              strokeDasharray="4 6"
              strokeWidth="1.5"
            />
            <path
              d="M98 20L108 26L98 32M46 124L36 118L46 112"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <span className="absolute top-8 left-3 rounded-(--radius-2) border border-border bg-card px-2 py-1 text-[9px] shadow-sm">
            Run
          </span>
          <span className="absolute right-1 bottom-8 rounded-(--radius-2) border border-border bg-card px-2 py-1 text-[9px] shadow-sm">
            Review
          </span>
        </div>
      );
    case "autoresearch":
      return (
        <div className="w-full max-w-56 rounded-(--radius-3) border border-border bg-gray-1 p-3 shadow-sm">
          <div className="flex items-center justify-between text-[9px] text-gray-10">
            <span>API latency</span>
            <span className="font-mono text-green-11">-9%</span>
          </div>
          <svg viewBox="0 0 160 58" className="mt-3 w-full text-green-10">
            <title>Metric improves across attempts</title>
            <path
              d="M4 10L36 20L66 17L98 36L128 31L156 49"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
            />
            {[4, 36, 66, 98, 128, 156].map((x, index) => (
              <circle
                key={x}
                cx={x}
                cy={[10, 20, 17, 36, 31, 49][index]}
                r="2.5"
                fill="currentColor"
              />
            ))}
          </svg>
          <div className="mt-2 flex items-center gap-1.5 text-[9px] text-gray-10">
            <ChartLineUpIcon size={11} /> Measure, change, repeat
          </div>
        </div>
      );
    case "build-task":
      return (
        <div className="w-full max-w-56 overflow-hidden rounded-(--radius-3) border border-border bg-gray-1 shadow-sm">
          <div className="flex items-center justify-between border-border border-b px-3 py-2 text-[10px]">
            <span className="font-medium">Update onboarding</span>
            <span className="flex items-center gap-1 text-(--accent-11)">
              <CircleNotchIcon
                size={11}
                className="animate-spin motion-reduce:animate-none"
              />
              Working
            </span>
          </div>
          <div className="grid gap-2.5 p-3 text-[9px]">
            <span className="flex items-center gap-2">
              <CheckCircleIcon
                size={12}
                weight="fill"
                className="text-green-9"
              />
              Review existing patterns
            </span>
            <span className="flex items-center gap-2">
              <CircleNotchIcon
                size={12}
                className="animate-spin text-(--accent-10) motion-reduce:animate-none"
              />
              Build the new view
            </span>
            <span className="flex items-center gap-2 text-gray-9">
              <span className="size-3 rounded-full border border-gray-7" /> Run
              checks
            </span>
          </div>
        </div>
      );
    case "investigate":
      return (
        <div className="w-full max-w-56 rounded-(--radius-3) border border-border bg-gray-1 p-3 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-[10px]">
            <CircleNotchIcon
              size={12}
              className="animate-spin text-(--accent-10) motion-reduce:animate-none"
            />
            <span className="font-medium">Investigating</span>
          </div>
          <div className="grid gap-2">
            {["Inspect trend", "Compare sessions", "Collect evidence"].map(
              (label, index) => (
                <div key={label} className="flex items-center gap-2 text-[9px]">
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      index === 0 ? "bg-green-9" : "border border-gray-7",
                    )}
                  />
                  <span>{label}</span>
                </div>
              ),
            )}
          </div>
        </div>
      );
    case "scheduled-run":
      return (
        <div className="w-full max-w-56 rounded-(--radius-3) border border-border bg-gray-1 p-3 shadow-sm">
          <div className="mb-3 flex items-center justify-between text-[10px]">
            <span className="flex items-center gap-1.5 font-medium">
              <ArrowsClockwiseIcon size={12} /> Weekly review
            </span>
            <CircleNotchIcon
              size={11}
              className="animate-spin text-(--accent-10) motion-reduce:animate-none"
            />
          </div>
          <div className="rounded-(--radius-2) border border-border bg-card p-2 text-[9px]">
            <div className="mb-2 h-1.5 w-4/5 rounded-full bg-gray-7" />
            <div className="h-1.5 w-1/2 rounded-full bg-gray-5" />
          </div>
          <div className="mt-2 text-[8px] text-gray-9">
            Run 08 · in progress
          </div>
        </div>
      );
    case "experiment":
      return (
        <div className="w-full max-w-56 overflow-hidden rounded-(--radius-3) border border-border bg-gray-1 shadow-sm">
          <div className="flex items-center justify-between border-border border-b px-3 py-2 text-[10px]">
            <span className="font-medium">Attempt 04</span>
            <span className="font-mono text-green-11">+3.2%</span>
          </div>
          <div className="grid grid-cols-[1fr_auto] gap-3 p-3">
            <div className="flex h-16 items-end gap-1.5">
              {["h-5", "h-8", "h-7", "h-11", "h-14"].map((height) => (
                <span
                  key={height}
                  className={cn("flex-1 rounded-t bg-(--accent-7)", height)}
                />
              ))}
            </div>
            <CircleNotchIcon
              size={13}
              className="mt-1 animate-spin text-(--accent-10) motion-reduce:animate-none"
            />
          </div>
        </div>
      );
    case "code-change":
      return (
        <div className="w-full max-w-56 rounded-(--radius-3) border border-border bg-gray-1 p-3 font-mono shadow-sm">
          <div className="mb-3 flex items-center gap-1.5 text-[9px] text-gray-10">
            <FileCodeIcon size={11} /> settings.tsx
          </div>
          <div className="grid gap-2">
            <div className="h-2 w-4/5 rounded-sm bg-red-5" />
            <div className="h-2 w-full rounded-sm bg-green-5" />
            <div className="h-2 w-3/4 rounded-sm bg-green-5" />
          </div>
          <div className="mt-3 flex gap-2 font-sans text-[9px]">
            <span className="rounded bg-green-3 px-1.5 py-0.5 text-green-11">
              +24
            </span>
            <span className="rounded bg-red-3 px-1.5 py-0.5 text-red-11">
              -3
            </span>
          </div>
        </div>
      );
    case "report":
      return (
        <div className="w-full max-w-56 rounded-(--radius-3) border border-border bg-gray-1 p-3 shadow-sm">
          <div className="mb-3 flex items-center gap-1.5 font-medium text-[10px]">
            <FileTextIcon size={12} /> Findings
          </div>
          <div className="grid gap-2">
            <div className="h-1.5 w-full rounded-full bg-gray-7" />
            <div className="h-1.5 w-5/6 rounded-full bg-gray-6" />
            <div className="h-1.5 w-2/3 rounded-full bg-gray-6" />
          </div>
          <div className="mt-4 rounded-(--radius-2) border border-border bg-card px-2 py-1.5 text-[8px] text-gray-10">
            3 linked sources
          </div>
        </div>
      );
    case "canvas":
      return (
        <div className="w-full max-w-56 overflow-hidden rounded-(--radius-3) border border-border bg-gray-1 shadow-sm">
          <div className="flex items-center gap-1.5 border-border border-b px-3 py-2 font-medium text-[10px]">
            <SquaresFourIcon size={12} /> Experiment results
          </div>
          <div className="grid grid-cols-[1.2fr_0.8fr] gap-2 p-3">
            <div className="flex h-20 items-end gap-1 rounded-(--radius-2) border border-border bg-card px-2 pt-3">
              {["h-5", "h-8", "h-7", "h-12", "h-14"].map((height) => (
                <span
                  key={height}
                  className={cn("flex-1 rounded-t bg-(--accent-7)", height)}
                />
              ))}
            </div>
            <div className="flex flex-col gap-2 rounded-(--radius-2) border border-border bg-card p-2">
              <FileTextIcon size={11} className="text-gray-9" />
              <div className="h-1.5 w-full rounded-full bg-gray-6" />
              <div className="h-1.5 w-4/5 rounded-full bg-gray-5" />
              <div className="h-1.5 w-3/5 rounded-full bg-gray-5" />
            </div>
          </div>
        </div>
      );
  }
}

interface CycleStageViewProps {
  stage: CycleStage;
  onOpenDestination: OnboardingCycleFlowLayoutProps["onOpenDestination"];
  controls?: ReactNode;
}

function CycleStageView({
  stage,
  onOpenDestination,
  controls,
}: CycleStageViewProps) {
  const action = stage.action;

  return (
    <article className="min-w-0">
      <div
        className="flex h-52 items-center justify-center overflow-hidden rounded-(--radius-4) border border-border bg-card p-5 shadow-sm"
        aria-hidden
      >
        {renderPreview(stage.preview)}
      </div>
      <div className="mt-4 min-h-40">
        <div className="flex min-h-6 items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-gray-9 text-xs">
            <span>{stage.label}</span>
            {stage.badge && <Badge variant="default">{stage.badge}</Badge>}
          </div>
          {controls}
        </div>
        <h2 className="mt-1 font-semibold text-lg">{stage.title}</h2>
        <p className="mt-2 text-gray-11 text-sm leading-6">
          {stage.description}
        </p>
        {action && (
          <Button
            nativeButton={false}
            variant="outline"
            size="sm"
            className="mt-4 active:scale-[0.98] motion-reduce:transform-none"
            data-attr={`onboarding-cycle-open-${action.destination}`}
            render={
              // biome-ignore lint/a11y/useAnchorContent: Base UI adds the button text to this anchor.
              <a
                href={action.href}
                aria-label={`${action.label} in a new tab`}
                onClick={(event) => {
                  event.preventDefault();
                  onOpenDestination(action.destination, action.href);
                }}
              />
            }
          >
            {action.label}
          </Button>
        )}
      </div>
    </article>
  );
}

interface CyclingState {
  activeIndex: number;
  manuallyPaused: boolean;
  timerDurationMs: number;
  timerRun: number;
  choose: (index: number) => void;
  toggle: () => void;
}

function useCyclingState(
  count: number,
  paused: boolean,
  prefersReducedMotion: boolean,
  initialDelayMs: number,
): CyclingState {
  const [activeIndex, setActiveIndex] = useState(0);
  const [manuallyPaused, setManuallyPaused] = useState(false);
  const [timerRun, setTimerRun] = useState(0);
  const [timerDurationMs, setTimerDurationMs] = useState(initialDelayMs);
  const remainingMs = useRef(initialDelayMs);
  const startedAt = useRef<number | null>(null);
  const stopped = paused || manuallyPaused;

  useEffect(() => {
    if (prefersReducedMotion || stopped) return;

    startedAt.current = performance.now();
    const timer = window.setTimeout(() => {
      startedAt.current = null;
      remainingMs.current = CYCLE_DURATION_MS;
      setTimerDurationMs(CYCLE_DURATION_MS);
      setActiveIndex((current) => (current + 1) % count);
      setTimerRun(timerRun + 1);
    }, remainingMs.current);

    return () => {
      window.clearTimeout(timer);
      if (startedAt.current === null) return;
      remainingMs.current = Math.max(
        0,
        remainingMs.current - (performance.now() - startedAt.current),
      );
      startedAt.current = null;
    };
  }, [count, prefersReducedMotion, stopped, timerRun]);

  const choose = (index: number): void => {
    remainingMs.current = CYCLE_DURATION_MS;
    setTimerDurationMs(CYCLE_DURATION_MS);
    setActiveIndex(index);
    setTimerRun((current) => current + 1);
  };

  const toggle = (): void => {
    if (prefersReducedMotion) {
      choose((activeIndex + 1) % count);
      return;
    }
    setManuallyPaused((current) => !current);
  };

  return {
    activeIndex,
    manuallyPaused,
    timerDurationMs,
    timerRun,
    choose,
    toggle,
  };
}

interface CycleControlProps {
  activeIndex: number;
  count: number;
  itemLabel: string;
  manuallyPaused: boolean;
  paused: boolean;
  prefersReducedMotion: boolean;
  timerDurationMs: number;
  timerRun: number;
  onChoose: (index: number) => void;
  onToggle: () => void;
}

function CycleControl({
  activeIndex,
  count,
  itemLabel,
  manuallyPaused,
  paused,
  prefersReducedMotion,
  timerDurationMs,
  timerRun,
  onChoose,
  onToggle,
}: CycleControlProps) {
  const itemIds = ["first", "second", "third", "fourth"].slice(0, count);

  return (
    <div
      className="onboarding-cycle-flow__control flex items-center gap-2"
      data-paused={paused || prefersReducedMotion ? "true" : "false"}
    >
      <fieldset
        className="m-0 flex items-center gap-1 border-0 p-0"
        aria-label={`Choose ${itemLabel}`}
      >
        {itemIds.map((itemId, index) => (
          <button
            key={itemId}
            type="button"
            aria-label={`Show ${itemLabel} ${index + 1}`}
            aria-pressed={activeIndex === index}
            data-attr={`onboarding-cycle-${itemLabel}-${index + 1}`}
            className={cn(
              "size-1.5 rounded-full outline-none transition-[background-color,transform] duration-150 ease-out hover:scale-125 focus-visible:ring-(--accent-8) focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-90 motion-reduce:transform-none motion-reduce:transition-none",
              activeIndex === index ? "bg-(--accent-9)" : "bg-gray-6",
            )}
            onClick={() => onChoose(index)}
          />
        ))}
      </fieldset>
      <button
        type="button"
        aria-label={
          prefersReducedMotion
            ? `Show next ${itemLabel}`
            : manuallyPaused
              ? `Resume ${itemLabel} cycle`
              : `Pause ${itemLabel} cycle`
        }
        className="flex size-5 items-center justify-center rounded-full text-gray-10 outline-none transition-[background-color,transform] duration-150 ease-out hover:bg-fill-hover focus-visible:ring-(--accent-8) focus-visible:ring-2 active:scale-[0.92] motion-reduce:transform-none motion-reduce:transition-none"
        onClick={onToggle}
      >
        <span className="relative size-4" aria-hidden>
          <svg viewBox="0 0 12 12" className="size-4">
            <title>{`${itemLabel} cycle progress`}</title>
            <circle
              cx="6"
              cy="6"
              r="4"
              fill="none"
              stroke="currentColor"
              strokeOpacity="0.2"
              strokeWidth="1"
            />
            <circle
              key={`${activeIndex}-${timerRun}`}
              className="onboarding-cycle-flow__timer-progress text-(--accent-10)"
              style={{ animationDuration: `${timerDurationMs}ms` }}
              cx="6"
              cy="6"
              r="4"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="1"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center">
            {prefersReducedMotion ? (
              <ArrowsClockwiseIcon size={8} />
            ) : manuallyPaused ? (
              <PlayIcon size={7} weight="fill" />
            ) : (
              <PauseIcon size={7} weight="fill" />
            )}
          </span>
        </span>
      </button>
    </div>
  );
}

interface AnimatedStageProps extends CycleStageViewProps {
  motionKey: string;
  prefersReducedMotion: boolean;
}

function AnimatedStage({
  motionKey,
  prefersReducedMotion,
  ...stageProps
}: AnimatedStageProps) {
  const { controls, ...cycleStageProps } = stageProps;
  const transition = prefersReducedMotion
    ? { duration: 0 }
    : { duration: 0.16, ease: [0.23, 1, 0.32, 1] as const };

  return (
    <div className="relative">
      {controls && (
        <div className="absolute top-56 right-0 z-10">{controls}</div>
      )}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={motionKey}
          initial={
            prefersReducedMotion
              ? false
              : { opacity: 0, transform: "translateY(5px)" }
          }
          animate={{ opacity: 1, transform: "translateY(0)" }}
          exit={
            prefersReducedMotion
              ? { opacity: 1 }
              : { opacity: 0, transform: "translateY(-3px)" }
          }
          transition={transition}
        >
          <CycleStageView {...cycleStageProps} />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export function OnboardingCycleFlowLayout({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingCycleFlowLayoutProps) {
  const visiblePaths = selfDrivingAvailable
    ? cyclePaths
    : cyclePaths.filter((path) => path.input.preview !== "self-driving");
  const resultStages = [
    cyclePaths[0].result,
    cyclePaths[1].result,
    cyclePaths[3].result,
  ];
  const prefersReducedMotion = Boolean(useReducedMotion());
  const [inputHovered, setInputHovered] = useState(false);
  const [inputFocusWithin, setInputFocusWithin] = useState(false);
  const [resultHovered, setResultHovered] = useState(false);
  const [resultFocusWithin, setResultFocusWithin] = useState(false);
  const inputCycle = useCyclingState(
    visiblePaths.length,
    inputHovered || inputFocusWithin,
    prefersReducedMotion,
    CYCLE_DURATION_MS,
  );
  const resultCycle = useCyclingState(
    resultStages.length,
    resultHovered || resultFocusWithin,
    prefersReducedMotion,
    CYCLE_DURATION_MS / 2,
  );

  const activePath = visiblePaths[inputCycle.activeIndex % visiblePaths.length];
  const activeResult =
    resultStages[resultCycle.activeIndex % resultStages.length];

  return (
    <div
      className="onboarding-cycle-flow mx-auto max-w-5xl pb-12"
      data-attr="onboarding-cycle-flow-layout"
    >
      <header className="mb-10">
        <h1 className="font-bold text-xl">How work moves through Desktop</h1>
        <p className="mt-1 max-w-2xl text-gray-11 text-sm leading-5">
          Inputs and results change independently. The agent adapts its work to
          the active input.
        </p>
      </header>

      <div className="grid @3xl:grid-cols-[minmax(0,1fr)_2rem_minmax(0,1fr)_2rem_minmax(0,1fr)] grid-cols-1 gap-5">
        <div
          data-attr="onboarding-cycle-input-stage"
          onPointerEnter={() => setInputHovered(true)}
          onPointerLeave={() => setInputHovered(false)}
          onFocusCapture={() => setInputFocusWithin(true)}
          onBlurCapture={(event) => {
            if (
              !event.currentTarget.contains(event.relatedTarget as Node | null)
            ) {
              setInputFocusWithin(false);
            }
          }}
        >
          <AnimatedStage
            motionKey={activePath.input.title}
            prefersReducedMotion={prefersReducedMotion}
            stage={activePath.input}
            onOpenDestination={onOpenDestination}
            controls={
              <CycleControl
                activeIndex={inputCycle.activeIndex}
                count={visiblePaths.length}
                itemLabel="input"
                manuallyPaused={inputCycle.manuallyPaused}
                paused={
                  inputHovered || inputFocusWithin || inputCycle.manuallyPaused
                }
                prefersReducedMotion={prefersReducedMotion}
                timerDurationMs={inputCycle.timerDurationMs}
                timerRun={inputCycle.timerRun}
                onChoose={inputCycle.choose}
                onToggle={inputCycle.toggle}
              />
            }
          />
        </div>
        <div className="@3xl:mt-24 flex @3xl:h-auto h-8 items-center justify-center">
          <ArrowRightIcon
            size={18}
            className="@3xl:rotate-0 rotate-90 text-gray-8"
            aria-hidden
          />
        </div>
        <AnimatedStage
          motionKey={activePath.agent.title}
          prefersReducedMotion={prefersReducedMotion}
          stage={activePath.agent}
          onOpenDestination={onOpenDestination}
        />
        <div className="@3xl:mt-24 flex @3xl:h-auto h-8 items-center justify-center">
          <ArrowRightIcon
            size={18}
            className="@3xl:rotate-0 rotate-90 text-gray-8"
            aria-hidden
          />
        </div>
        <div
          data-attr="onboarding-cycle-result-stage"
          onPointerEnter={() => setResultHovered(true)}
          onPointerLeave={() => setResultHovered(false)}
          onFocusCapture={() => setResultFocusWithin(true)}
          onBlurCapture={(event) => {
            if (
              !event.currentTarget.contains(event.relatedTarget as Node | null)
            ) {
              setResultFocusWithin(false);
            }
          }}
        >
          <AnimatedStage
            motionKey={activeResult.title}
            prefersReducedMotion={prefersReducedMotion}
            stage={activeResult}
            onOpenDestination={onOpenDestination}
            controls={
              <CycleControl
                activeIndex={resultCycle.activeIndex}
                count={resultStages.length}
                itemLabel="result"
                manuallyPaused={resultCycle.manuallyPaused}
                paused={
                  resultHovered ||
                  resultFocusWithin ||
                  resultCycle.manuallyPaused
                }
                prefersReducedMotion={prefersReducedMotion}
                timerDurationMs={resultCycle.timerDurationMs}
                timerRun={resultCycle.timerRun}
                onChoose={resultCycle.choose}
                onToggle={resultCycle.toggle}
              />
            }
          />
        </div>
      </div>
    </div>
  );
}
