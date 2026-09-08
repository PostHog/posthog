import {
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

interface OnboardingCompactFlowLayoutProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

interface CompactNodeProps {
  title: string;
  description: string;
  preview: ReactNode;
  destination?: OnboardingLandingDestination;
  href?: string;
  badge?: string;
  alignment?: "row" | "centered" | "branch";
  onOpenDestination: OnboardingCompactFlowLayoutProps["onOpenDestination"];
}

const interactiveNodeClassName =
  "rounded-(--radius-3) outline-none transition-[background-color,transform] duration-150 ease-out hover:bg-fill-hover active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-(--accent-8) focus-visible:ring-offset-2 motion-reduce:transform-none motion-reduce:transition-none";

function CompactNode({
  title,
  description,
  preview,
  destination,
  href,
  badge,
  alignment = "row",
  onOpenDestination,
}: CompactNodeProps) {
  const rootClassName =
    alignment === "centered"
      ? "grid grid-cols-[minmax(0,1fr)_6rem_minmax(0,1fr)] items-start gap-x-3"
      : alignment === "branch"
        ? "flex items-start gap-3 @3xl:flex-col @3xl:items-center @3xl:text-center"
        : "flex items-start gap-3";
  const tileClassName = alignment === "centered" ? "col-start-2" : "";
  const textClassName = alignment === "centered" ? "col-start-3" : "";
  const headingClassName = alignment === "branch" ? "@3xl:justify-center" : "";

  const content = (
    <>
      <div
        className={`flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-(--radius-3) border border-border bg-card p-2.5 shadow-sm transition-[border-color,box-shadow] duration-150 ease-out group-hover:border-(--accent-8) group-hover:shadow-md motion-reduce:transition-none ${tileClassName}`}
      >
        {preview}
      </div>
      <div className={`min-w-0 py-1 ${textClassName}`}>
        <div className={`flex items-center gap-1.5 ${headingClassName}`}>
          <h3 className="font-semibold text-sm leading-5">{title}</h3>
          {badge && <Badge variant="default">{badge}</Badge>}
          {destination && (
            <ArrowSquareOutIcon
              size={12}
              className="shrink-0 text-gray-9"
              aria-hidden
            />
          )}
        </div>
        <p className="mt-1 max-w-48 text-gray-11 text-xs leading-5">
          {description}
        </p>
      </div>
    </>
  );

  if (!destination || !href) {
    return (
      <div className={rootClassName} data-alignment={alignment}>
        {content}
      </div>
    );
  }

  return (
    <a
      href={href}
      aria-label={`Open ${title} in a new tab`}
      data-attr={`onboarding-compact-open-${destination}`}
      data-alignment={alignment}
      className={`group -m-2 p-2 text-foreground no-underline ${rootClassName} ${interactiveNodeClassName}`}
      onClick={(event) => {
        event.preventDefault();
        onOpenDestination(destination, href);
      }}
    >
      {content}
    </a>
  );
}

function Junction({ label }: { label?: string }) {
  return (
    <div className="relative flex h-14 items-center justify-center" aria-hidden>
      <div className="h-full w-px bg-border" />
      <div className="absolute flex size-5 items-center justify-center rounded-full border border-border bg-gray-1 font-medium text-[10px] text-gray-9">
        {label ?? "+"}
      </div>
    </div>
  );
}

function BranchConnector({
  direction,
  branches = 3,
}: {
  direction: "merge" | "split";
  branches?: 2 | 3;
}) {
  const path =
    direction === "merge"
      ? branches === 3
        ? "M16 0V12Q16 22 26 22H50M50 0V36M84 0V12Q84 22 74 22H50"
        : "M25 0V12Q25 22 35 22H50M75 0V12Q75 22 65 22H50M50 22V36"
      : "M50 0V14M50 14H26Q16 14 16 24V36M50 14V36M50 14H74Q84 14 84 24V36";
  const junctionTop = direction === "merge" ? "top-[61%]" : "top-[39%]";

  return (
    <div className="relative @3xl:block hidden h-14" aria-hidden>
      <svg
        viewBox="0 0 100 36"
        preserveAspectRatio="none"
        className="h-full w-full text-gray-7"
      >
        <title>{direction === "merge" ? "Paths merge" : "Paths split"}</title>
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span
        className={`-translate-x-1/2 -translate-y-1/2 absolute left-1/2 size-2 rounded-full bg-(--accent-9) ${junctionTop}`}
      />
    </div>
  );
}

const UserInputPreview = (
  <div
    className="w-full rounded-(--radius-2) border border-border bg-gray-1 p-1.5"
    aria-hidden
  >
    <div className="h-1.5 w-3/4 rounded-full bg-gray-7" />
    <div className="mt-1.5 flex items-center border-border border-t pt-1.5">
      <div className="h-1 w-8 rounded-full bg-gray-5" />
      <span className="ml-auto flex size-4 items-center justify-center rounded bg-(--accent-9) text-white">
        <PaperPlaneRightIcon size={8} weight="fill" />
      </span>
    </div>
  </div>
);

const SelfDrivingPreview = (
  <div className="grid w-full gap-1" aria-hidden>
    {[
      { id: "signup", priority: "P1", width: "w-8" },
      { id: "invite", priority: "P2", width: "w-10" },
      { id: "queries", priority: "P2", width: "w-7" },
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

const LoopsPreview = (
  <div className="relative size-full" aria-hidden>
    <svg viewBox="0 0 72 72" className="size-full text-blue-9">
      <title>Loop circuit</title>
      <path
        d="M20 15H52Q61 15 61 24V48Q61 57 52 57H20Q11 57 11 48V24Q11 15 20 15Z"
        fill="none"
        stroke="currentColor"
        strokeDasharray="2 3"
      />
      <path d="M49 12L54 15L49 18" fill="none" stroke="currentColor" />
      <path d="M23 60L18 57L23 54" fill="none" stroke="currentColor" />
    </svg>
    <span className="absolute top-2 left-2 rounded border border-border bg-card px-1 py-0.5 text-[7px]">
      Run
    </span>
    <span className="absolute right-2 bottom-2 rounded border border-border bg-card px-1 py-0.5 text-[7px]">
      Review
    </span>
  </div>
);

const AutoresearchPreview = (
  <div className="w-full" aria-hidden>
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
      {["2,6", "15,11", "27,9", "40,18", "51,16", "62,23"].map((point) => {
        const [cx, cy] = point.split(",");
        return (
          <circle key={point} cx={cx} cy={cy} r="1.5" fill="currentColor" />
        );
      })}
    </svg>
    <div className="mt-1 flex items-center gap-1 text-[7px] text-gray-9">
      <ChartLineUpIcon size={9} />
      Measure, change, repeat
    </div>
  </div>
);

const AgentWorkPreview = (
  <div className="w-full" aria-hidden>
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

const CodeChangePreview = (
  <div className="w-full font-mono" aria-hidden>
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

const CanvasPreview = (
  <div className="w-full" aria-hidden>
    <div className="mb-1.5 flex items-center gap-1 text-[7px] text-gray-9">
      <SquaresFourIcon size={9} />
      Activation
    </div>
    <div className="flex h-9 items-end gap-1 rounded border border-border bg-gray-1 px-1.5 pt-1">
      {[
        { id: "mon", height: "h-3" },
        { id: "tue", height: "h-5" },
        { id: "wed", height: "h-4" },
        { id: "thu", height: "h-7" },
        { id: "fri", height: "h-6" },
      ].map(({ id, height }) => (
        <span
          key={id}
          className={`flex-1 rounded-t bg-(--accent-7) ${height}`}
        />
      ))}
    </div>
  </div>
);

const ReportPreview = (
  <div className="w-full" aria-hidden>
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

export function OnboardingCompactFlowLayout({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingCompactFlowLayoutProps) {
  return (
    <div
      className="mx-auto max-w-5xl pb-12"
      data-attr="onboarding-compact-flow-layout"
    >
      <header className="mb-10">
        <h1 className="font-bold text-xl">From idea to result</h1>
        <p className="mt-1 max-w-xl text-gray-11 text-sm leading-5">
          Start work yourself or let Desktop find it. Agents turn each path into
          something you can review and use.
        </p>
      </header>

      <section aria-label="Start work" className="mx-auto max-w-3xl">
        <CompactNode
          title="User input"
          description="Describe a task and send it to an agent."
          preview={UserInputPreview}
          destination="tasks"
          href="/new"
          alignment="centered"
          onOpenDestination={onOpenDestination}
        />
      </section>

      <Junction label="or" />

      <div className="mb-6 text-center font-medium text-gray-10 text-xs">
        Or automate the input
      </div>
      <section
        aria-label="Automated work"
        className={`grid grid-cols-1 @3xl:gap-10 gap-8 ${selfDrivingAvailable ? "@3xl:grid-cols-3" : "@3xl:grid-cols-2"}`}
      >
        {selfDrivingAvailable && (
          <CompactNode
            title="Self-driving"
            description="Pick important work from a prioritized inbox."
            preview={SelfDrivingPreview}
            destination="self-driving"
            href="/inbox"
            alignment="branch"
            onOpenDestination={onOpenDestination}
          />
        )}
        <CompactNode
          title="Loops"
          description="Run a task again on a schedule or trigger."
          preview={LoopsPreview}
          badge="Coming soon"
          alignment="branch"
          onOpenDestination={onOpenDestination}
        />
        <CompactNode
          title="Autoresearch"
          description="Measure a result and improve it across attempts."
          preview={AutoresearchPreview}
          alignment="branch"
          onOpenDestination={onOpenDestination}
        />
      </section>

      <div className="mt-3">
        <BranchConnector
          direction="merge"
          branches={selfDrivingAvailable ? 3 : 2}
        />
      </div>
      <div className="@3xl:hidden">
        <Junction />
      </div>

      <section aria-label="Agent work" className="mx-auto max-w-3xl">
        <CompactNode
          title="Agent work"
          description="Follow progress in a thread and guide the work."
          preview={AgentWorkPreview}
          destination="agents"
          href="/agents"
          alignment="centered"
          onOpenDestination={onOpenDestination}
        />
      </section>

      <div className="mt-3">
        <BranchConnector direction="split" />
      </div>
      <div className="@3xl:hidden">
        <Junction />
      </div>

      <div className="mb-6 text-center font-medium text-gray-10 text-xs">
        Review the result
      </div>
      <section
        aria-label="Results"
        className="grid @3xl:grid-cols-3 grid-cols-1 @3xl:gap-10 gap-8"
      >
        <CompactNode
          title="Code change"
          description="Review the files and checks before you merge."
          preview={CodeChangePreview}
          alignment="branch"
          onOpenDestination={onOpenDestination}
        />
        <CompactNode
          title="Canvas"
          description="Turn the result into a shared view or tool."
          preview={CanvasPreview}
          destination="canvases"
          href="/canvases"
          alignment="branch"
          onOpenDestination={onOpenDestination}
        />
        <CompactNode
          title="Report"
          description="Read a clear summary with supporting evidence."
          preview={ReportPreview}
          alignment="branch"
          onOpenDestination={onOpenDestination}
        />
      </section>
    </div>
  );
}
