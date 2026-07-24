import { MagnifyingGlass } from "@phosphor-icons/react";
import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import { Spinner } from "@posthog/quill";
import { Badge, Skeleton, Text } from "@radix-ui/themes";

export interface SessionActivity {
  status: "connecting" | "connected" | "disconnected" | "error";
  isPromptPending: boolean;
  isCompacting: boolean;
}

export function PreBaselineState({
  run,
  sessionActivity,
}: {
  run: AutoresearchRun;
  sessionActivity: SessionActivity | null;
}) {
  const live = run.status === "running" || run.status === "interrupted";
  const activity = baselineActivity(run, sessionActivity);

  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex items-start gap-3 rounded-md border border-blue-6 bg-blue-2 px-3 py-3">
        {live && (
          <span className="relative mt-0.5 size-5 shrink-0">
            <Spinner className="size-5 motion-safe:animate-spin motion-reduce:animate-none" />
          </span>
        )}
        <div>
          <Text as="div" size="2" weight="medium">
            {activity.title}
          </Text>
          <Text as="p" size="1" color="gray" className="mt-0.5 leading-4">
            {activity.description}
          </Text>
        </div>
      </div>

      <BaselineStatCards
        maxIterations={run.config.maxIterations}
        loading={live}
      />

      {live ? (
        <BaselineDashboardSkeleton />
      ) : (
        <div className="rounded-md border border-gray-5 bg-gray-2 px-3 py-4 text-center">
          <Text size="1" color="gray">
            No metric report was recorded for this run.
          </Text>
        </div>
      )}

      {run.researchFindings.length > 0 && <ResearchFindings run={run} />}
    </div>
  );
}

function baselineActivity(
  run: AutoresearchRun,
  session: SessionActivity | null,
): { title: string; description: string } {
  if (run.status === "paused") {
    return {
      title: "Baseline measurement paused",
      description: "Resume the run to collect the first metric value.",
    };
  }
  if (run.status === "interrupted") {
    return {
      title: "Reconnecting before baseline measurement",
      description:
        "Autoresearch will resume automatically when the agent is available.",
    };
  }
  if (run.status !== "running") {
    return {
      title: "Run ended before the baseline was reported",
      description: run.lastError ?? "The agent did not return a metric value.",
    };
  }
  if (!session || session.status === "connecting") {
    return {
      title: "Connecting to the agent",
      description:
        "The baseline measurement starts when the task session is ready.",
    };
  }
  if (session.isCompacting) {
    return {
      title: "Preparing agent context",
      description:
        "The baseline measurement will continue after context compaction.",
    };
  }
  if (session.isPromptPending) {
    if (run.researchFindings.length > 0) {
      const latest = run.researchFindings[run.researchFindings.length - 1];
      return {
        title: "Researching the codebase",
        description:
          latest?.nextStep ??
          "The agent is continuing its investigation before measuring the baseline.",
      };
    }
    return {
      title: "Establishing the baseline",
      description:
        "The agent is running the measurement defined in the task prompt.",
    };
  }
  return {
    title: "Waiting for the first metric report",
    description:
      "The dashboard will populate when the agent reports the baseline value.",
  };
}

function ResearchFindings({ run }: { run: AutoresearchRun }) {
  const groups = Map.groupBy(
    run.researchFindings,
    (finding) => finding.area ?? "General",
  );
  return (
    <section className="rounded-md border border-gray-5">
      <div className="flex items-center gap-2 border-gray-5 border-b px-3 py-2">
        <MagnifyingGlass size={14} className="text-gray-10" />
        <Text size="2" weight="medium">
          Codebase research
        </Text>
        <Text size="1" color="gray">
          {run.researchFindings.length}{" "}
          {run.researchFindings.length === 1 ? "finding" : "findings"}
        </Text>
      </div>
      <div className="grid gap-2 p-2 sm:grid-cols-2">
        {Array.from(groups.entries()).map(([area, findings]) => (
          <section
            key={area}
            className="rounded-sm border border-gray-5 bg-gray-1"
          >
            <div className="flex items-center justify-between gap-2 border-gray-5 border-b px-2.5 py-2">
              <Badge color="gray" size="1" variant="soft">
                {area}
              </Badge>
              <Text size="1" color="gray">
                {findings.length}
              </Text>
            </div>
            <ol className="divide-y divide-gray-5">
              {findings.map((finding) => (
                <li key={finding.index} className="px-2.5 py-2">
                  <Text size="1" weight="medium">
                    {finding.summary}
                  </Text>
                  <Text as="p" size="1" color="gray" className="mt-1 leading-4">
                    {finding.finding}
                  </Text>
                  {finding.nextStep && (
                    <Text
                      as="p"
                      size="1"
                      className="mt-1 text-blue-11 leading-4"
                    >
                      Next: {finding.nextStep}
                    </Text>
                  )}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </section>
  );
}

function BaselineDashboardSkeleton() {
  return (
    <output
      className="flex flex-col gap-4"
      aria-label="Loading autoresearch metrics"
    >
      <div className="flex h-[220px] flex-col justify-between rounded-md border border-gray-5 bg-gray-2 p-3">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-2/3" />
        </div>
        <div className="flex items-end gap-2">
          {["h-8", "h-12", "h-16", "h-20", "h-24"].map((height) => (
            <Skeleton key={height} className={`w-full ${height}`} />
          ))}
        </div>
      </div>

      <div className="rounded-md border border-gray-5 p-3">
        <div className="flex items-center justify-between gap-4">
          <Skeleton className="h-3 w-8" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-40" />
        </div>
      </div>
    </output>
  );
}

function BaselineStatCards({
  maxIterations,
  loading,
}: {
  maxIterations: number;
  loading: boolean;
}) {
  return (
    <section
      aria-label="Autoresearch metric summary"
      className="grid @min-[360px]:grid-cols-2 @min-[700px]:grid-cols-4 grid-cols-1 gap-2"
    >
      {[
        ["Best", "w-16"],
        ["Last", "w-16"],
        ["Iterations", "w-12"],
        ["Target", "w-14"],
      ].map(([title, width]) => (
        <div key={title} className="rounded-md border border-gray-5 p-3">
          <Text as="div" size="1" color="gray">
            {title}
          </Text>
          <BaselineStatValue
            title={title}
            width={width}
            maxIterations={maxIterations}
            loading={loading}
          />
        </div>
      ))}
    </section>
  );
}

function BaselineStatValue({
  title,
  width,
  maxIterations,
  loading,
}: {
  title: string;
  width: string;
  maxIterations: number;
  loading: boolean;
}) {
  if (title === "Iterations") {
    return (
      <Text as="div" size="4" weight="medium" className="mt-1">
        0 / {maxIterations}
      </Text>
    );
  }
  if (loading) return <Skeleton className={`mt-2 h-6 ${width}`} />;
  return (
    <Text as="div" size="4" color="gray" className="mt-1">
      —
    </Text>
  );
}
