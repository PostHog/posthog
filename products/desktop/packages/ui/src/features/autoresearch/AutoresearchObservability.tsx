import {
  Binoculars,
  Check,
  Code,
  Compass,
  Lightbulb,
  ListChecks,
  MagnifyingGlass,
  Terminal,
  TestTube,
} from "@phosphor-icons/react";
import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import { getAutoresearchElapsedMs } from "@posthog/core/autoresearch/stats";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Badge as QuillBadge,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { AcpMessage } from "@posthog/shared";
import { Badge, Progress, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useState } from "react";
import { formatDuration } from "../sessions/components/GeneratingIndicator";
import {
  type AutoresearchActivityKind,
  analyzeAutoresearchActivity,
} from "./autoresearchActivity";

export function AutoresearchObservability({
  run,
  events,
}: {
  run: AutoresearchRun;
  events: AcpMessage[];
}) {
  const live = run.endedAt === null && run.status === "running";
  const now = useLiveNow(live);
  const observationEnd = run.endedAt ?? run.pausedAt ?? now;
  const activity = useMemo(
    () =>
      analyzeAutoresearchActivity(
        events,
        run.startedAt,
        run.endedAt,
        observationEnd,
        {
          live,
          pauseIntervals: run.pauseIntervals,
          pausedDurationMs: run.pausedDurationMs,
        },
      ),
    [
      events,
      live,
      observationEnd,
      run.endedAt,
      run.pauseIntervals,
      run.pausedDurationMs,
      run.startedAt,
    ],
  );
  const lastIteration = run.iterations.at(-1);
  const hypothesis =
    activity.currentPlan?.hypothesis ?? lastIteration?.hypothesis;
  const plan = activity.currentPlan?.plan ?? lastIteration?.plan;
  const approach = activity.currentPlan?.approach ?? lastIteration?.approach;
  const observedTime = (
    Object.keys(activity.timeByKind) as AutoresearchActivityKind[]
  ).sort(
    (left, right) => activity.timeByKind[right] - activity.timeByKind[left],
  );

  return (
    <div className="@container grid gap-3">
      <div className="grid @min-[700px]:grid-cols-2 grid-cols-1 gap-3">
        <section className="rounded-md border border-gray-5 p-3">
          <SectionTitle
            icon={<Lightbulb size={15} />}
            title="Current experiment"
          />
          <Detail
            label="Hypothesis"
            value={hypothesis ?? "Waiting for the agent to state a hypothesis."}
          />
          <Detail
            label="Iteration plan"
            value={
              plan ?? "The next focused experiment has not been announced yet."
            }
          />
          {approach && (
            <div className="mt-3">
              <Badge color="gray" variant="soft">
                {approach}
              </Badge>
            </div>
          )}
        </section>

        <section className="rounded-md border border-gray-5 p-3">
          <SectionTitle icon={<Compass size={15} />} title="Observed time" />
          <div className="mt-3 flex flex-col gap-2.5">
            {observedTime.map((kind) => (
              <TimeRow
                key={kind}
                kind={kind}
                value={activity.timeByKind[kind]}
                total={Math.max(1, getAutoresearchElapsedMs(run, now))}
              />
            ))}
          </div>
        </section>
      </div>

      <CurrentFindings run={run} />

      <TooltipProvider delay={300}>
        <Collapsible
          defaultOpen
          className="min-w-0 max-w-full overflow-hidden rounded-md border border-gray-5 bg-transparent hover:bg-transparent data-open:bg-transparent"
        >
          <CollapsibleTrigger className="p-3 hover:bg-gray-2 aria-expanded:bg-transparent">
            <SectionTitle
              icon={<ListChecks size={15} />}
              title="Live timeline"
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="min-w-0 max-w-full overflow-hidden px-3 pt-3 pb-3">
            {activity.items.length === 0 ? (
              <EmptyTimelineState
                live={run.status === "running" || run.status === "interrupted"}
              />
            ) : (
              <ol className="relative ml-1 min-w-0 max-w-full border-gray-5 border-l">
                {activity.items.map((item) => (
                  <li
                    key={item.id}
                    className="relative grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2.5 pb-3 pl-4 last:pb-0"
                  >
                    <span className="-left-[7px] absolute flex size-3.5 items-center justify-center rounded-full border border-gray-5 bg-gray-1 text-gray-10">
                      <ActivityMarker item={item} />
                    </span>
                    <ActivityIcon kind={item.kind} />
                    <div
                      className="min-w-0 flex-1 overflow-hidden"
                      data-timeline-command-column
                    >
                      <Tooltip>
                        <TooltipTrigger
                          render={activityLabelTrigger(item.command)}
                        >
                          {activityLabelContent(item.command, item.label)}
                        </TooltipTrigger>
                        <TooltipContent
                          side="top"
                          className="wrap-break-word max-w-[min(560px,calc(100vw-2rem))] whitespace-pre-wrap"
                        >
                          {item.label}
                        </TooltipContent>
                      </Tooltip>
                      <div
                        className="mt-0.5 flex min-w-0 items-center gap-1.5 overflow-hidden"
                        data-timeline-details
                      >
                        <Text
                          as="div"
                          size="1"
                          color="gray"
                          className="min-w-0 truncate text-[11px]"
                        >
                          {TIME_LABEL[item.kind]} ·{" "}
                          <time dateTime={new Date(item.at).toISOString()}>
                            {formatCommandTime(item.at)}
                          </time>{" "}
                          · {formatTimelineTime(item.at - run.startedAt)}
                        </Text>
                        <ActivityStatusBadge item={item} />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CollapsibleContent>
        </Collapsible>
      </TooltipProvider>
    </div>
  );
}

const TIMELINE_SKELETON_ROWS = [
  { id: "current", commandWidth: "w-3/5", detailWidth: "w-2/5" },
  { id: "recent", commandWidth: "w-4/5", detailWidth: "w-1/3" },
  { id: "earlier", commandWidth: "w-1/2", detailWidth: "w-2/5" },
];

function TimelineLoadingState() {
  return (
    <output aria-label="Loading live timeline">
      <ol className="relative ml-1 border-gray-5 border-l">
        {TIMELINE_SKELETON_ROWS.map((row, index) => (
          <li
            key={row.id}
            className="relative grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2.5 pb-3 pl-4 last:pb-0"
          >
            <span className="-left-[7px] absolute flex size-3.5 items-center justify-center rounded-full border border-gray-5 bg-gray-1">
              <span className="size-1.5 rounded-full bg-gray-6" />
            </span>
            <Skeleton className="size-3.5 rounded-sm" />
            <div className="min-w-0 pt-px">
              <Skeleton className={`h-3 ${row.commandWidth}`} />
              <div className="mt-1.5 flex items-center gap-1.5">
                <Skeleton className={`h-2.5 ${row.detailWidth}`} />
                {index === 0 && (
                  <Skeleton className="ml-auto h-5 w-10 rounded-full" />
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </output>
  );
}

function EmptyTimelineState({ live }: { live: boolean }) {
  if (live) return <TimelineLoadingState />;
  return (
    <Text as="p" size="1" color="gray">
      No timeline activity was recorded.
    </Text>
  );
}

function CurrentFindings({ run }: { run: AutoresearchRun }) {
  const findings = run.researchFindings.slice(-3).reverse();
  return (
    <section className="rounded-md border border-gray-5 p-3">
      <SectionTitle
        icon={<MagnifyingGlass size={15} />}
        title="Current findings"
      />
      {findings.length === 0 ? (
        <Text as="p" size="1" color="gray" className="mt-2">
          Findings appear here as the agent records research checkpoints.
        </Text>
      ) : (
        <ol className="mt-2 divide-y divide-gray-5">
          {findings.map((finding) => (
            <li key={finding.index} className="py-2 first:pt-0 last:pb-0">
              <div className="flex items-center gap-2">
                <Text size="1" weight="medium" className="min-w-0 flex-1">
                  {finding.summary}
                </Text>
                {finding.area && <FindingAreaBadge area={finding.area} />}
              </div>
              <Text as="p" size="1" color="gray" className="mt-1 leading-4">
                {finding.finding}
              </Text>
              {finding.nextStep && (
                <Text as="p" size="1" className="mt-1 text-blue-11 leading-4">
                  Next: {finding.nextStep}
                </Text>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function FindingAreaBadge({ area }: { area: string }) {
  return (
    <TooltipProvider delay={300}>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="min-w-0 max-w-32 shrink-0 rounded-sm focus-visible:outline-2 focus-visible:outline-blue-8 focus-visible:outline-offset-1"
            />
          }
        >
          <Badge
            color="gray"
            size="1"
            variant="soft"
            className="block max-w-full truncate"
          >
            {area}
          </Badge>
        </TooltipTrigger>
        <TooltipContent side="top">{area}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function activityLabelTrigger(command: boolean) {
  const typography = command ? "font-mono text-[11px]" : "text-xs";
  const background = command ? "bg-gray-3 px-1.5 py-0.5" : "bg-transparent";
  return (
    <button
      type="button"
      className={`block w-full min-w-0 max-w-full truncate rounded-sm text-left leading-4 ${typography} ${background} focus-visible:outline-2 focus-visible:outline-blue-8 focus-visible:outline-offset-1`}
    />
  );
}

function activityLabelContent(command: boolean, label: string) {
  if (command) {
    return <code>{label}</code>;
  }
  return <span>{label}</span>;
}

function SectionTitle({
  icon,
  title,
}: {
  icon: React.ReactNode;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2 text-gray-11">
      {icon}
      <h3 className="font-medium text-sm">{title}</h3>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3">
      <Text as="div" size="1" color="gray">
        {label}
      </Text>
      <Text as="p" size="2" className="mt-0.5 leading-5">
        {value}
      </Text>
    </div>
  );
}

const TIME_LABEL: Record<AutoresearchActivityKind, string> = {
  research: "Research",
  implementation: "Implementation",
  measurement: "Measurement",
  execution: "Command execution",
  reasoning: "Reasoning and coordination",
};

function TimeRow({
  kind,
  value,
  total,
}: {
  kind: AutoresearchActivityKind;
  value: number;
  total: number;
}) {
  const percentage = Math.min(
    100,
    Math.max(0, Math.round((value / total) * 100)),
  );
  return (
    <div data-observed-kind={kind}>
      <div className="mb-1 flex items-center justify-between gap-3">
        <Text size="1">{TIME_LABEL[kind]}</Text>
        <Text size="1" color="gray" className="tabular-nums">
          {formatDuration(value, 0)}
        </Text>
      </div>
      <Progress
        value={percentage}
        size="1"
        color="gray"
        aria-label={`${TIME_LABEL[kind]} observed time`}
      />
    </div>
  );
}

function ActivityIcon({ kind }: { kind: AutoresearchActivityKind }) {
  let icon = <Binoculars size={14} />;
  if (kind === "research") icon = <MagnifyingGlass size={14} />;
  if (kind === "implementation") icon = <Code size={14} />;
  if (kind === "measurement") icon = <TestTube size={14} />;
  if (kind === "execution") icon = <Terminal size={14} />;
  return (
    <span
      className="flex h-5 w-3.5 shrink-0 items-center justify-center"
      data-activity-icon
    >
      {icon}
    </span>
  );
}

function ActivityMarker({
  item,
}: {
  item: { active: boolean; running: boolean };
}) {
  if (item.active) {
    return (
      <span className="relative flex size-2 items-center justify-center">
        <span className="absolute size-2 rounded-full bg-blue-9/50 motion-safe:animate-ping" />
        <span className="relative size-1.5 rounded-full bg-blue-9" />
      </span>
    );
  }
  if (item.running) {
    return <span className="size-1.5 rounded-full bg-gray-8" />;
  }
  return <Check size={9} weight="bold" />;
}

function ActivityStatusBadge({
  item,
}: {
  item: { active: boolean; running: boolean };
}) {
  if (item.active) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="ml-auto shrink-0 rounded-sm focus-visible:outline-2 focus-visible:outline-blue-8 focus-visible:outline-offset-1"
            />
          }
        >
          <QuillBadge variant="info">Now</QuillBadge>
        </TooltipTrigger>
        <TooltipContent side="top">
          Most recently started command that has not finished
        </TooltipContent>
      </Tooltip>
    );
  }
  if (item.running) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="ml-auto shrink-0 rounded-sm focus-visible:outline-2 focus-visible:outline-blue-8 focus-visible:outline-offset-1"
            />
          }
        >
          <QuillBadge variant="default" className="text-gray-10">
            Background
          </QuillBadge>
        </TooltipTrigger>
        <TooltipContent side="top">
          Started earlier and is still running
        </TooltipContent>
      </Tooltip>
    );
  }
  return null;
}

function formatTimelineTime(elapsed: number): string {
  return `+${formatDuration(Math.max(0, elapsed), 0)}`;
}

const commandTimeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

function formatCommandTime(timestamp: number): string {
  return commandTimeFormat.format(timestamp);
}

function useLiveNow(live: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [live]);
  return now;
}
