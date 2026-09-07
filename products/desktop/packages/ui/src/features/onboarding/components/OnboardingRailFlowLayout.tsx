import {
  ArrowDownIcon,
  ArrowSquareOutIcon,
  ChartLineUpIcon,
  CircleNotchIcon,
  FileCodeIcon,
  FileTextIcon,
  PaperPlaneRightIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import type { ReactNode } from "react";

interface OnboardingRailFlowLayoutProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

type RailItemKind =
  | "user-input"
  | "self-driving"
  | "loops"
  | "autoresearch"
  | "agent-work"
  | "code-change"
  | "canvas"
  | "report";

interface RailItem {
  kind: RailItemKind;
  title: string;
  description: string;
  destination?: OnboardingLandingDestination;
  href?: string;
  badge?: string;
}

const inputItems: RailItem[] = [
  {
    kind: "user-input",
    title: "User input",
    description:
      "Describe a change in a new task, then send it to an agent when the brief is ready.",
    destination: "tasks",
    href: "/new",
  },
  {
    kind: "self-driving",
    title: "Self-driving",
    description:
      "Review a prioritized inbox of problems that Desktop found in your PostHog project.",
    destination: "self-driving",
    href: "/inbox",
  },
  {
    kind: "loops",
    title: "Loops",
    badge: "Coming soon",
    description:
      "Run the same task on a schedule. Each run starts with the latest context.",
  },
  {
    kind: "autoresearch",
    title: "Autoresearch",
    description:
      "Set a metric. The agent tests a change, measures the result, and starts another attempt.",
  },
];

const resultItems: RailItem[] = [
  {
    kind: "code-change",
    title: "Code change",
    description:
      "Review the changed files, test results, and implementation notes before you merge.",
  },
  {
    kind: "canvas",
    title: "Canvas",
    description:
      "Keep the result as a shared document, data view, or small tool in a space.",
    destination: "canvases",
    href: "/canvases",
  },
  {
    kind: "report",
    title: "Report",
    description:
      "Read a text summary that explains the finding and includes supporting evidence.",
  },
];

const agentItem: RailItem = {
  kind: "agent-work",
  title: "Agent work",
  description:
    "Follow each step in the thread. Add guidance with Send to agent while the task runs.",
  destination: "agents",
  href: "/agents",
};

const interactiveNodeClassName =
  "rounded-(--radius-3) outline-none transition-[background-color,transform] duration-150 ease-out hover:bg-fill-hover active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-(--accent-8) focus-visible:ring-offset-2 motion-reduce:transform-none motion-reduce:transition-none";

function previewFor(kind: RailItemKind): ReactNode {
  switch (kind) {
    case "user-input":
      return (
        <div className="w-full rounded-(--radius-2) border border-border bg-gray-1 p-1.5">
          <div className="h-1.5 w-4/5 rounded-full bg-gray-7" />
          <div className="mt-1.5 flex items-center border-border border-t pt-1.5">
            <div className="h-1 w-9 rounded-full bg-gray-5" />
            <span className="ml-auto flex size-4 items-center justify-center rounded bg-(--accent-9) text-white">
              <PaperPlaneRightIcon size={8} weight="fill" />
            </span>
          </div>
        </div>
      );
    case "self-driving":
      return (
        <div className="grid w-full gap-1">
          {[
            { id: "signup", priority: "P1", width: "w-9" },
            { id: "invite", priority: "P2", width: "w-11" },
            { id: "queries", priority: "P2", width: "w-8" },
          ].map(({ id, priority, width }) => (
            <div
              key={id}
              className="flex items-center gap-1 rounded border border-border bg-gray-1 px-1 py-1"
            >
              <span
                className={`rounded px-0.5 font-semibold text-[7px] ${priority === "P1" ? "bg-orange-3 text-orange-11" : "bg-yellow-3 text-yellow-11"}`}
              >
                {priority}
              </span>
              <span className={`h-1 rounded-full bg-gray-7 ${width}`} />
            </div>
          ))}
        </div>
      );
    case "loops":
      return (
        <div className="relative size-full">
          <svg viewBox="0 0 72 72" className="size-full text-blue-9">
            <title>Loop circuit</title>
            <path
              d="M20 15H52Q61 15 61 24V48Q61 57 52 57H20Q11 57 11 48V24Q11 15 20 15Z"
              fill="none"
              stroke="currentColor"
              strokeDasharray="2 3"
            />
            <path
              d="M49 12L54 15L49 18M23 60L18 57L23 54"
              fill="none"
              stroke="currentColor"
            />
          </svg>
          <span className="absolute top-2 left-2 rounded border border-border bg-card px-1 py-0.5 text-[7px]">
            Run
          </span>
          <span className="absolute right-2 bottom-2 rounded border border-border bg-card px-1 py-0.5 text-[7px]">
            Review
          </span>
        </div>
      );
    case "autoresearch":
      return (
        <div className="w-full">
          <div className="flex items-center justify-between text-[7px] text-gray-9">
            <span>API latency</span>
            <span className="font-mono text-green-11">-9%</span>
          </div>
          <svg viewBox="0 0 64 28" className="mt-1 w-full text-green-10">
            <title>Metric improves across attempts</title>
            <path
              d="M2 6L15 11L27 9L40 18L51 16L62 23"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="mt-1 flex items-center gap-1 text-[7px] text-gray-9">
            <ChartLineUpIcon size={9} />
            Measure, change, repeat
          </div>
        </div>
      );
    case "agent-work":
      return (
        <div className="w-full">
          <div className="flex items-center gap-1 border-border border-b pb-1.5">
            <CircleNotchIcon
              size={10}
              className="animate-spin text-(--accent-10) motion-reduce:animate-none"
            />
            <span className="font-medium text-[8px]">Working</span>
          </div>
          <div className="mt-1.5 grid gap-1.5">
            {["w-10", "w-12", "w-8"].map((width, index) => (
              <div key={width} className="flex items-center gap-1">
                <span
                  className={`size-1.5 rounded-full ${index === 0 ? "bg-green-9" : "border border-gray-7"}`}
                />
                <span className={`h-1 rounded-full bg-gray-7 ${width}`} />
              </div>
            ))}
          </div>
        </div>
      );
    case "code-change":
      return (
        <div className="w-full font-mono">
          <div className="mb-1.5 flex items-center gap-1 text-[7px] text-gray-9">
            <FileCodeIcon size={9} />
            settings.tsx
          </div>
          <div className="grid gap-1">
            <div className="h-1.5 w-11 rounded-sm bg-red-5" />
            <div className="h-1.5 w-14 rounded-sm bg-green-5" />
            <div className="h-1.5 w-9 rounded-sm bg-green-5" />
          </div>
        </div>
      );
    case "canvas":
      return (
        <div className="w-full">
          <div className="mb-1.5 flex items-center gap-1 text-[7px] text-gray-9">
            <SquaresFourIcon size={9} />
            Activation
          </div>
          <div className="flex h-9 items-end gap-1 rounded border border-border bg-gray-1 px-1.5 pt-1">
            {["h-3", "h-5", "h-4", "h-7", "h-6"].map((height) => (
              <span
                key={height}
                className={`flex-1 rounded-t bg-(--accent-7) ${height}`}
              />
            ))}
          </div>
        </div>
      );
    case "report":
      return (
        <div className="w-full">
          <div className="mb-2 flex items-center gap-1 text-[7px] text-gray-9">
            <FileTextIcon size={9} />
            Findings
          </div>
          <div className="grid gap-1.5">
            <div className="h-1 w-full rounded-full bg-gray-7" />
            <div className="h-1 w-4/5 rounded-full bg-gray-6" />
            <div className="h-1 w-3/5 rounded-full bg-gray-6" />
          </div>
        </div>
      );
  }
}

export function OnboardingRailFlowLayout({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingRailFlowLayoutProps) {
  const visibleInputs = selfDrivingAvailable
    ? inputItems
    : inputItems.filter((item) => item.kind !== "self-driving");

  const renderItem = (item: RailItem): ReactNode => {
    const destination = item.destination;
    const href = item.href;
    const content = (
      <>
        <div
          className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-(--radius-3) border border-border bg-card p-2.5 shadow-sm transition-[border-color,box-shadow] duration-150 ease-out group-hover:border-(--accent-8) group-hover:shadow-md motion-reduce:transition-none"
          aria-hidden
        >
          {previewFor(item.kind)}
        </div>
        <div className="min-w-0 py-1.5">
          <div className="flex items-center gap-1.5">
            <h3 className="font-semibold text-base leading-5">{item.title}</h3>
            {item.badge && <Badge variant="default">{item.badge}</Badge>}
            {destination && (
              <ArrowSquareOutIcon
                size={13}
                className="shrink-0 text-gray-9"
                aria-hidden
              />
            )}
          </div>
          <p className="mt-2 max-w-2xl text-gray-11 text-sm leading-6">
            {item.description}
          </p>
        </div>
      </>
    );

    if (!destination || !href) {
      return (
        <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-6">
          {content}
        </div>
      );
    }

    return (
      <a
        href={href}
        aria-label={`Open ${item.title} in a new tab`}
        data-attr={`onboarding-rail-open-${destination}`}
        className={`group -m-2 grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-6 p-2 text-foreground no-underline ${interactiveNodeClassName}`}
        onClick={(event) => {
          event.preventDefault();
          onOpenDestination(destination, href);
        }}
      >
        {content}
      </a>
    );
  };

  const renderConnector = (
    label: "or" | "then" | "results",
    key: string,
  ): ReactNode => (
    <div
      key={key}
      className="grid h-14 grid-cols-[6rem_minmax(0,1fr)] gap-6"
      aria-hidden
    >
      <div className="relative flex justify-center">
        <div className="h-full w-px bg-border" />
        <span className="-translate-y-1/2 absolute top-1/2 flex min-w-6 items-center justify-center rounded-full border border-border bg-gray-1 px-1.5 py-1 font-medium text-[9px] text-gray-9">
          {label === "then" ? <ArrowDownIcon size={10} /> : label}
        </span>
      </div>
      {label === "results" && (
        <div className="flex items-center font-medium text-gray-10 text-xs">
          Possible results
        </div>
      )}
    </div>
  );

  return (
    <div
      className="mx-auto max-w-4xl pb-12"
      data-attr="onboarding-rail-flow-layout"
    >
      <header className="mb-10">
        <h1 className="font-bold text-xl">How work moves through Desktop</h1>
        <p className="mt-1 max-w-2xl text-gray-11 text-sm leading-5">
          Choose how work starts. Each path runs through an agent and produces a
          result that you can review.
        </p>
      </header>

      <section aria-labelledby="rail-start-heading">
        <h2
          id="rail-start-heading"
          className="mb-6 font-semibold text-gray-10 text-xs uppercase tracking-wide"
        >
          Start work
        </h2>
        <div className="relative">
          <div
            className="-bottom-3 -left-3 -top-3 pointer-events-none absolute w-30 rounded-(--radius-4) border border-gray-7 border-dashed"
            aria-hidden
          />
          <div className="relative grid">
            {visibleInputs.map((item, index) => (
              <div key={item.kind}>
                {renderItem(item)}
                {index < visibleInputs.length - 1 &&
                  renderConnector("or", `${item.kind}-or`)}
              </div>
            ))}
          </div>
        </div>
      </section>

      {renderConnector("then", "agent-connector")}

      <section aria-label="Agent work">{renderItem(agentItem)}</section>

      {renderConnector("results", "result-connector")}

      <section aria-label="Results" className="grid gap-8">
        {resultItems.map((item) => (
          <div key={item.kind}>{renderItem(item)}</div>
        ))}
      </section>
    </div>
  );
}
