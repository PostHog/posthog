import {
  ArrowRightIcon,
  ArrowSquareOutIcon,
  ChartLineUpIcon,
  CheckIcon,
  CircleNotchIcon,
  CodeIcon,
  FileCodeIcon,
  FileTextIcon,
  ListChecksIcon,
  PaperPlaneRightIcon,
  RobotIcon,
  SquaresFourIcon,
  TimerIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import type { ReactNode } from "react";

interface OnboardingFlowLayoutProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

const linkedCardClassName =
  "transition-[background-color,border-color,transform] duration-150 ease-out hover:border-(--accent-8) hover:bg-fill-hover active:scale-[0.98] motion-reduce:transform-none motion-reduce:transition-none";

function FlowCard({
  title,
  description,
  icon,
  preview,
  destination,
  href,
  badge,
  onOpenDestination,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  preview: ReactNode;
  destination?: OnboardingLandingDestination;
  href?: string;
  badge?: string;
  onOpenDestination: OnboardingFlowLayoutProps["onOpenDestination"];
}) {
  const content = (
    <>
      <div className="min-h-32 overflow-hidden border-border border-b bg-gray-2 p-3">
        {preview}
      </div>
      <div className="p-3.5">
        <div className="flex items-center gap-2">
          <span className="text-gray-10" aria-hidden>
            {icon}
          </span>
          <h3 className="font-semibold text-sm">{title}</h3>
          {badge && <Badge variant="default">{badge}</Badge>}
          {destination && (
            <ArrowSquareOutIcon
              size={12}
              className="ml-auto shrink-0 text-gray-10"
              aria-hidden
            />
          )}
        </div>
        <p className="mt-1.5 text-gray-11 text-xs leading-4">{description}</p>
      </div>
    </>
  );

  if (!destination || !href) {
    return (
      <div className="overflow-hidden rounded-(--radius-3) border border-border bg-card">
        {content}
      </div>
    );
  }

  return (
    <a
      href={href}
      aria-label={`Open ${title} in a new tab`}
      data-attr={`onboarding-flow-open-${destination}`}
      className={`overflow-hidden rounded-(--radius-3) border border-border bg-card text-foreground no-underline ${linkedCardClassName}`}
      onClick={(event) => {
        event.preventDefault();
        onOpenDestination(destination, href);
      }}
    >
      {content}
    </a>
  );
}

function StageConnector({ begin = "0s" }: { begin?: string }) {
  return (
    <svg
      viewBox="0 0 32 52"
      className="mx-auto h-13 w-8 overflow-visible text-gray-8"
      aria-hidden
    >
      <title>Flow connector</title>
      <path
        d="M16 0V43M11 38L16 43L21 38"
        fill="none"
        stroke="currentColor"
        strokeDasharray="3 4"
        strokeLinecap="round"
      />
      <circle
        cx="16"
        cy="3"
        r="3"
        fill="var(--accent-9)"
        className="motion-reduce:hidden"
      >
        <animate
          attributeName="cy"
          values="3;42"
          dur="2s"
          begin={begin}
          repeatCount="indefinite"
        />
        <animate
          attributeName="opacity"
          values="0;1;1;0"
          dur="2s"
          begin={begin}
          repeatCount="indefinite"
        />
      </circle>
    </svg>
  );
}

const UserInputPreview = (
  <div
    className="flex h-full min-h-28 flex-col justify-end rounded-(--radius-2) border border-border bg-gray-1 p-2.5"
    aria-hidden
  >
    <div className="mb-2 text-gray-12 text-xs leading-4">
      Add SSO settings for workspace admins
    </div>
    <div className="flex items-center gap-2 border-border border-t pt-2">
      <span className="text-[10px] text-gray-10">Ask an agent...</span>
      <span className="ml-auto flex size-6 items-center justify-center rounded-(--radius-2) bg-(--accent-9) text-white">
        <PaperPlaneRightIcon size={12} weight="fill" />
      </span>
    </div>
  </div>
);

const SelfDrivingPreview = (
  <div
    className="flex h-full min-h-28 flex-col gap-1.5 rounded-(--radius-2) border border-border bg-gray-1 p-2"
    aria-hidden
  >
    {[
      ["P1", "Signup errors increased", "Error tracking"],
      ["P2", "Users abandon invite flow", "Product analytics"],
      ["P2", "Slow queries on activity feed", "Logs"],
    ].map(([priority, title, source]) => (
      <div
        key={title}
        className="flex items-center gap-2 rounded border border-border bg-card px-2 py-1.5"
      >
        <span
          className={`rounded px-1 py-0.5 font-semibold text-[9px] ${priority === "P1" ? "bg-orange-3 text-orange-11" : "bg-yellow-3 text-yellow-11"}`}
        >
          {priority}
        </span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-gray-12">
          {title}
        </span>
        <span className="@xl:inline hidden text-[9px] text-gray-9">
          {source}
        </span>
      </div>
    ))}
  </div>
);

const LoopsPreview = (
  <div
    className="relative h-28 overflow-hidden rounded-(--radius-2) border border-border bg-gray-1"
    aria-hidden
  >
    <svg
      viewBox="0 0 320 100"
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full text-blue-8"
    >
      <title>Loop flow</title>
      <path
        d="M55 24H265Q284 24 284 43V57Q284 76 265 76H55Q36 76 36 57V43Q36 24 55 24Z"
        fill="none"
        stroke="currentColor"
        strokeDasharray="3 4"
      />
      <circle r="4" fill="var(--blue-9)" className="motion-reduce:hidden">
        <animateMotion
          dur="4s"
          repeatCount="indefinite"
          path="M55 24H265Q284 24 284 43V57Q284 76 265 76H55Q36 76 36 57V43Q36 24 55 24Z"
        />
      </circle>
    </svg>
    <div className="absolute inset-x-4 top-3 flex items-center justify-between">
      <span className="rounded border border-border bg-card px-2 py-1 text-[9px]">
        Schedule
      </span>
      <span className="rounded border border-border bg-card px-2 py-1 text-[9px]">
        Agent runs
      </span>
    </div>
    <div className="absolute inset-x-4 bottom-3 flex items-center justify-between">
      <span className="rounded border border-border bg-card px-2 py-1 text-[9px]">
        Wait
      </span>
      <span className="rounded border border-border bg-card px-2 py-1 text-[9px]">
        Report
      </span>
    </div>
  </div>
);

const AutoresearchPreview = (
  <div
    className="relative h-28 overflow-hidden rounded-(--radius-2) border border-border bg-gray-1 p-2.5"
    aria-hidden
  >
    <div className="flex items-center justify-between">
      <span className="text-[9px] text-gray-10">Metric: API latency</span>
      <span className="font-mono text-[10px] text-green-11">820 → 740 ms</span>
    </div>
    <div className="mt-3 grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-1">
      {[
        ["Hypothesis", "Cache reads"],
        ["Change", "Edit code"],
        ["Measure", "Run metric"],
      ].map(([label, value], index) => (
        <div className="contents" key={label}>
          <div className="rounded border border-border bg-card px-1.5 py-2 text-center">
            <div className="font-semibold text-[9px] text-gray-12">{label}</div>
            <div className="mt-0.5 truncate text-[8px] text-gray-9">
              {value}
            </div>
          </div>
          {index < 2 && <ArrowRightIcon size={10} className="text-green-10" />}
        </div>
      ))}
    </div>
    <div className="mt-2 flex items-center justify-center gap-1 text-[8px] text-green-11">
      <CircleNotchIcon
        size={10}
        className="animate-spin motion-reduce:animate-none"
      />
      Start the next attempt
    </div>
  </div>
);

const AgentWorkPreview = (
  <div className="grid @3xl:grid-cols-[1.4fr_1fr] gap-3" aria-hidden>
    <div className="overflow-hidden rounded-(--radius-2) border border-border bg-gray-1">
      <div className="flex items-center gap-2 border-border border-b px-3 py-2.5">
        <CircleNotchIcon
          size={14}
          className="animate-spin text-(--accent-10) motion-reduce:animate-none"
        />
        <span className="font-medium text-xs">Add SSO settings</span>
        <span className="ml-auto text-[10px] text-gray-10">Working</span>
      </div>
      <div className="grid gap-2 p-3">
        <div className="flex items-center gap-2 text-[10px] text-gray-11">
          <CheckIcon size={11} className="text-green-10" />
          Read the settings code
        </div>
        <div className="flex items-center gap-2 text-[10px] text-gray-12">
          <CircleNotchIcon
            size={11}
            className="animate-spin text-(--accent-10) motion-reduce:animate-none"
          />
          Edit 3 files
        </div>
        <div className="flex items-center gap-2 text-[10px] text-gray-9">
          <span className="ml-0.5 size-2 rounded-full border border-gray-7" />
          Run checks
        </div>
      </div>
    </div>
    <div className="flex flex-col rounded-(--radius-2) border border-border bg-gray-1 p-3">
      <div className="flex items-center gap-2 text-[10px] text-gray-10">
        <span className="font-medium text-gray-12">Thread</span>
        <span>2 replies</span>
      </div>
      <p className="mt-2 rounded bg-gray-3 px-2 py-1.5 text-[10px] text-gray-11">
        Include a test for the empty state.
      </p>
      <div className="mt-auto flex justify-end pt-2">
        <span className="inline-flex items-center gap-1 rounded border border-(--accent-7) bg-(--accent-2) px-2 py-1 text-(--accent-11) text-[9px]">
          <PaperPlaneRightIcon size={10} />
          Send to agent
        </span>
      </div>
    </div>
  </div>
);

const CodeChangesPreview = (
  <div
    className="h-28 overflow-hidden rounded-(--radius-2) border border-border bg-gray-1 font-mono"
    aria-hidden
  >
    <div className="flex items-center gap-1.5 border-border border-b px-2.5 py-2 text-[9px] text-gray-10">
      <FileCodeIcon size={11} />
      SettingsAccess.tsx
      <span className="ml-auto text-green-11">+18</span>
      <span className="text-red-11">-4</span>
    </div>
    <div className="grid text-[9px] leading-5">
      <div className="bg-red-3 px-2.5 text-red-11">
        - role === &quot;admin&quot;
      </div>
      <div className="bg-green-3 px-2.5 text-green-11">
        + canManageSSO(user)
      </div>
      <div className="bg-green-3 px-2.5 text-green-11">
        + &lt;SSOSettings /&gt;
      </div>
    </div>
  </div>
);

const CanvasPreview = (
  <div
    className="h-28 overflow-hidden rounded-(--radius-2) border border-border bg-gray-1 p-2.5"
    aria-hidden
  >
    <div className="mb-2 flex items-center gap-1.5 text-[9px] text-gray-11">
      <SquaresFourIcon size={11} />
      Activation overview
    </div>
    <div className="grid h-14 grid-cols-[1.3fr_1fr] gap-2">
      <div className="flex items-end gap-1 rounded border border-border bg-card px-2 pt-3 pb-2">
        {[
          ["one", 40],
          ["two", 62],
          ["three", 48],
          ["four", 78],
          ["five", 68],
          ["six", 88],
        ].map(([id, height]) => (
          <span
            key={id}
            className="flex-1 rounded-t-sm bg-(--accent-7)"
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
      <div className="rounded border border-border bg-card p-2">
        <div className="text-[8px] text-gray-9">Activated</div>
        <div className="mt-1 font-semibold text-xs">38%</div>
        <div className="mt-2 text-[8px] text-green-11">+6.2% this week</div>
      </div>
    </div>
  </div>
);

const ReportPreview = (
  <div
    className="h-28 overflow-hidden rounded-(--radius-2) border border-border bg-gray-1 p-2.5"
    aria-hidden
  >
    <div className="flex items-center gap-2">
      <span className="rounded bg-orange-3 px-1 py-0.5 font-semibold text-[8px] text-orange-11">
        P1
      </span>
      <span className="font-medium text-[10px]">Signup errors increased</span>
    </div>
    <div className="mt-2.5 space-y-1.5">
      <div className="h-1.5 w-11/12 rounded bg-gray-6" />
      <div className="h-1.5 w-4/5 rounded bg-gray-5" />
      <div className="h-1.5 w-3/5 rounded bg-gray-5" />
    </div>
    <div className="mt-3 flex items-center gap-1.5 text-[9px] text-gray-10">
      <CheckIcon size={10} className="text-green-10" />3 findings and next steps
    </div>
  </div>
);

export function OnboardingFlowLayout({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingFlowLayoutProps) {
  return (
    <div data-attr="onboarding-flow-layout" className="pb-8">
      <div className="mx-auto mb-7 max-w-2xl text-center">
        <h1 className="font-bold text-xl">How work moves through Desktop</h1>
        <p className="mt-1.5 text-gray-11 text-sm">
          Start the work yourself or let an automation find it. An agent does
          the work and gives you something to review.
        </p>
      </div>

      <section aria-labelledby="flow-start-heading">
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 id="flow-start-heading" className="font-semibold text-sm">
            1. Start the work
          </h2>
          <span className="text-gray-10 text-xs">Choose one</span>
        </div>
        <div className="grid @3xl:grid-cols-2 grid-cols-1 gap-3">
          <FlowCard
            title="User input"
            description="Describe a task, request a canvas, or send a message from a thread."
            icon={<ListChecksIcon size={17} />}
            preview={UserInputPreview}
            destination="tasks"
            href="/new"
            onOpenDestination={onOpenDestination}
          />
          {selfDrivingAvailable && (
            <FlowCard
              title="Self-driving"
              description="Review problems that PostHog finds in your product signals."
              icon={<TrayIcon size={17} />}
              preview={SelfDrivingPreview}
              destination="self-driving"
              href="/inbox"
              onOpenDestination={onOpenDestination}
            />
          )}
          <FlowCard
            title="Loops"
            description="Run the same agent task on a schedule or when an event occurs."
            icon={<TimerIcon size={17} />}
            preview={LoopsPreview}
            badge="Coming soon"
            onOpenDestination={onOpenDestination}
          />
          <FlowCard
            title="Autoresearch"
            description="Repeat a code change, measure its result, and use the result in the next attempt."
            icon={<ChartLineUpIcon size={17} />}
            preview={AutoresearchPreview}
            onOpenDestination={onOpenDestination}
          />
        </div>
      </section>

      <StageConnector />

      <section aria-labelledby="flow-agent-heading">
        <div className="overflow-hidden rounded-(--radius-3) border border-(--accent-7) bg-(--accent-a2)">
          <div className="grid @3xl:grid-cols-[14rem_1fr] @3xl:items-center gap-5 p-4">
            <div>
              <div className="flex items-center gap-2">
                <RobotIcon
                  size={18}
                  className="text-(--accent-11)"
                  aria-hidden
                />
                <h2 id="flow-agent-heading" className="font-semibold text-sm">
                  2. Agent work
                </h2>
              </div>
              <p className="mt-2 text-gray-11 text-xs leading-4">
                The agent plans the task, changes files, runs checks, and
                responds to messages from the thread.
              </p>
              <a
                href="/agents"
                aria-label="Open Agents in a new tab"
                data-attr="onboarding-flow-open-agents"
                className="mt-3 inline-flex items-center gap-1.5 text-(--accent-11) text-xs no-underline hover:underline"
                onClick={(event) => {
                  event.preventDefault();
                  onOpenDestination("agents", "/agents");
                }}
              >
                Open agents <ArrowSquareOutIcon size={11} />
              </a>
            </div>
            {AgentWorkPreview}
          </div>
        </div>
      </section>

      <StageConnector begin="0.7s" />

      <section aria-labelledby="flow-output-heading">
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 id="flow-output-heading" className="font-semibold text-sm">
            3. Review the output
          </h2>
          <span className="text-gray-10 text-xs">
            One task can create more than one
          </span>
        </div>
        <div className="grid @2xl:grid-cols-2 @4xl:grid-cols-3 grid-cols-1 gap-3">
          <FlowCard
            title="Code change"
            description="Review the diff and open its pull request."
            icon={<CodeIcon size={17} />}
            preview={CodeChangesPreview}
            onOpenDestination={onOpenDestination}
          />
          <FlowCard
            title="Canvas"
            description="Use a generated document, data view, or tool."
            icon={<SquaresFourIcon size={17} />}
            preview={CanvasPreview}
            destination="canvases"
            href="/canvases"
            onOpenDestination={onOpenDestination}
          />
          <FlowCard
            title="Report"
            description="Read the findings, evidence, and suggested next steps."
            icon={<FileTextIcon size={17} />}
            preview={ReportPreview}
            onOpenDestination={onOpenDestination}
          />
        </div>
      </section>
    </div>
  );
}
