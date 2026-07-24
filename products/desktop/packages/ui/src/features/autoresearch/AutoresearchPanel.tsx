import {
  ChartLineUp,
  Pause,
  Play,
  Plus,
  StopCircle,
} from "@phosphor-icons/react";
import type { AutoresearchService } from "@posthog/core/autoresearch/autoresearch";
import { AUTORESEARCH_SERVICE } from "@posthog/core/autoresearch/identifiers";
import type {
  AutoresearchRun,
  AutoresearchRunStatus,
} from "@posthog/core/autoresearch/schemas";
import { summarizeRun } from "@posthog/core/autoresearch/stats";
import { useServiceOptional } from "@posthog/di/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { MetricCard } from "@posthog/quill-charts";
import type { AcpMessage } from "@posthog/shared";
import { Badge, Button, Callout, Flex, Select, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useState } from "react";
import { useContextUsage } from "../sessions/hooks/useContextUsage";
import {
  getConfigOptionByCategory,
  useSessionStore,
} from "../sessions/sessionStore";
import { usePendingPermissionsForTask } from "../sessions/useSession";
import { AutoresearchConfigDialog } from "./AutoresearchConfigDialog";
import { AutoresearchObservability } from "./AutoresearchObservability";
import { AutoresearchRuntimeStats } from "./AutoresearchRuntimeStats";
import { IterationsTable } from "./IterationsTable";
import { MetricChart } from "./MetricChart";
import { metricNumberFormat, withMetricUnit } from "./metricFormat";
import { PreBaselineState } from "./PreBaselineState";
import {
  type AutoresearchModelOption,
  stageValueLabel,
  toStageSelectOptions,
} from "./stageModels";
import { useAutoresearchEnabled } from "./useAutoresearchEnabled";
import { useAutoresearchRuns } from "./useAutoresearchStore";

const EMPTY_SESSION_EVENTS: AcpMessage[] = [];

const STATUS_BADGE: Record<
  AutoresearchRunStatus,
  {
    color: "blue" | "amber" | "orange" | "green" | "gray" | "red";
    label: string;
  }
> = {
  running: { color: "blue", label: "Running" },
  paused: { color: "amber", label: "Paused" },
  interrupted: { color: "orange", label: "Interrupted" },
  completed: { color: "green", label: "Completed" },
  stopped: { color: "gray", label: "Stopped" },
  failed: { color: "red", label: "Failed" },
};

const END_REASON_LABEL: Record<string, string> = {
  "target-reached": "Target reached",
  "max-iterations": "Iteration budget spent",
  "stopped-by-user": "Stopped by user",
  "missing-report": "Agent stopped reporting the metric",
};

const INTERRUPTION_LABEL: Record<string, string> = {
  "session-error": "Agent session disconnected",
  "rate-limited": "Usage limit reached",
  "send-failed": "Couldn't reach the agent",
  "app-restart": "App restarted mid-run",
};

interface AutoresearchPanelProps {
  taskId: string;
}

export function AutoresearchPanel({ taskId }: AutoresearchPanelProps) {
  const service = useServiceOptional<AutoresearchService>(AUTORESEARCH_SERVICE);
  const runs = useAutoresearchRuns(taskId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const enabled = useAutoresearchEnabled();

  // Runs persist across app restarts; pull this task's history into the store.
  // Flag-gated so the feature stays dormant for ungated users; already-live
  // runs (flag revoked mid-session) keep their controls via the store.
  useEffect(() => {
    if (service && enabled) void service.hydrateTask(taskId);
  }, [service, enabled, taskId]);

  const modelOption = useSessionStore((state) => {
    const taskRunId = state.taskIdIndex[taskId];
    const session = taskRunId ? state.sessions[taskRunId] : undefined;
    return getConfigOptionByCategory(session?.configOptions, "model");
  });
  const thoughtOption = useSessionStore((state) => {
    const taskRunId = state.taskIdIndex[taskId];
    const session = taskRunId ? state.sessions[taskRunId] : undefined;
    return getConfigOptionByCategory(session?.configOptions, "thought_level");
  });
  const sessionActivity = useSessionStore((state) => {
    const taskRunId = state.taskIdIndex[taskId];
    const session = taskRunId ? state.sessions[taskRunId] : undefined;
    return session
      ? {
          status: session.status,
          isPromptPending: session.isPromptPending,
          isCompacting: session.isCompacting,
        }
      : null;
  });
  const sessionEvents = useSessionStore((state) => {
    const taskRunId = state.taskIdIndex[taskId];
    return taskRunId
      ? (state.sessions[taskRunId]?.events ?? EMPTY_SESSION_EVENTS)
      : EMPTY_SESSION_EVENTS;
  });
  const contextUsage = useContextUsage(sessionEvents);
  const modelOptions = useMemo(
    () => toStageSelectOptions(modelOption),
    [modelOption],
  );
  const effortOptions = useMemo(
    () => toStageSelectOptions(thoughtOption),
    [thoughtOption],
  );
  // What the session is actually on right now. The loop switches these
  // between stages, and this reflects the switches live.
  const liveModel =
    modelOption?.type === "select" ? (modelOption.currentValue ?? null) : null;
  const liveEffort =
    thoughtOption?.type === "select"
      ? (thoughtOption.currentValue ?? null)
      : null;

  const latestRun = runs[runs.length - 1] ?? null;
  const selectedRun =
    (selectedRunId && runs.find((run) => run.id === selectedRunId)) ||
    latestRun;
  const selectedRunUsage =
    selectedRun?.id === latestRun?.id &&
    (selectedRun?.status === "running" ||
      selectedRun?.status === "paused" ||
      selectedRun?.status === "interrupted")
      ? contextUsage
      : null;

  // A persisted panel tab can outlive access to the feature (web, or the
  // flag turned off). With runs already in the store, keep the dashboard
  // functional so live runs stay controllable.
  if (!service || (!enabled && runs.length === 0)) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ChartLineUp size={28} />
          </EmptyMedia>
          <EmptyTitle>Autoresearch unavailable</EmptyTitle>
          <EmptyDescription>
            Autoresearch is not available here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!selectedRun) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ChartLineUp size={28} />
          </EmptyMedia>
          <EmptyTitle>No autoresearch run</EmptyTitle>
          <EmptyDescription>
            This task wasn't created in autoresearch mode. Start one from the
            new task composer: arm the Autoresearch toggle, describe what to
            optimize and how to measure it, and submit.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <Flex
        direction="column"
        gap="4"
        p="4"
        className="@container mx-auto max-w-[760px]"
      >
        <RunHeader
          run={selectedRun}
          runs={runs}
          service={service}
          modelOptions={modelOptions}
          effortOptions={effortOptions}
          liveModel={liveModel}
          liveEffort={liveEffort}
          onSelectRun={setSelectedRunId}
          onNewRun={() => setDialogOpen(true)}
        />
        <PendingPermissionNotice taskId={taskId} run={selectedRun} />
        {selectedRun.iterations.length === 0 ? (
          <PreBaselineState
            run={selectedRun}
            sessionActivity={sessionActivity}
          />
        ) : (
          <>
            <RunStats run={selectedRun} />
            <MetricChart
              iterations={selectedRun.iterations}
              direction={selectedRun.config.direction}
              targetValue={selectedRun.config.targetValue}
              metricName={selectedRun.metricName ?? "the metric"}
              unit={selectedRun.metricUnit}
            />
            <IterationsTable
              iterations={selectedRun.iterations}
              direction={selectedRun.config.direction}
              unit={selectedRun.metricUnit}
            />
            {selectedRun.endedAt !== null && <RunSummary run={selectedRun} />}
          </>
        )}
        <AutoresearchRuntimeStats run={selectedRun} usage={selectedRunUsage} />
        <AutoresearchObservability run={selectedRun} events={sessionEvents} />
      </Flex>
      <AutoresearchConfigDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="New autoresearch run"
        description="Starts a fresh optimization loop in this task's session. The kickoff prompt is sent to the agent immediately."
        submitLabel="Start run"
        showInstructions
        modelOptions={modelOptions}
        effortOptions={effortOptions}
        initial={selectedRun.config}
        onSubmit={(values) => {
          service.startRun({
            taskId,
            direction: values.direction,
            targetValue: values.targetValue,
            maxIterations: values.maxIterations,
            implementModel: values.implementModel,
            measureModel: values.measureModel,
            implementEffort: values.implementEffort,
            measureEffort: values.measureEffort,
            instructions: values.instructions ?? "",
          });
          // Follow the new run even if a past run was selected.
          setSelectedRunId(null);
        }}
      />
    </div>
  );
}

function RunHeader({
  run,
  runs,
  service,
  modelOptions,
  effortOptions,
  liveModel,
  liveEffort,
  onSelectRun,
  onNewRun,
}: {
  run: AutoresearchRun;
  runs: AutoresearchRun[];
  service: AutoresearchService;
  modelOptions: AutoresearchModelOption[];
  effortOptions: AutoresearchModelOption[];
  liveModel: string | null;
  liveEffort: string | null;
  onSelectRun: (runId: string) => void;
  onNewRun: () => void;
}) {
  const badge = STATUS_BADGE[run.status];
  const isLive =
    run.status === "running" ||
    run.status === "paused" ||
    run.status === "interrupted";
  const isSplit =
    run.config.implementModel !== run.config.measureModel ||
    run.config.implementEffort !== run.config.measureEffort;

  return (
    <Flex direction="column" gap="1">
      <Flex align="center" justify="between" gap="3">
        <Flex align="center" gap="2" className="min-w-0">
          <Text size="3" weight="bold" className="truncate">
            {run.metricName ?? "Autoresearch"}
          </Text>
          <Badge color="gray" size="1">
            {run.config.direction}
          </Badge>
          {run.status !== "paused" && (
            <Badge color={badge.color} size="1">
              {badge.label}
            </Badge>
          )}
        </Flex>
        <Flex align="center" gap="2" className="shrink-0">
          {runs.length > 1 && (
            <Select.Root value={run.id} onValueChange={onSelectRun} size="1">
              <Select.Trigger variant="soft" />
              <Select.Content>
                {runs.map((candidate, index) => (
                  <Select.Item key={candidate.id} value={candidate.id}>
                    Run {index + 1}: {STATUS_BADGE[candidate.status].label}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          )}
          {(run.status === "running" || run.status === "interrupted") && (
            <Button
              size="1"
              variant="soft"
              color="gray"
              onClick={() => service.pauseRun(run.id)}
            >
              <Pause size={12} /> Pause
            </Button>
          )}
          {(run.status === "paused" || run.status === "interrupted") && (
            <Button
              size="1"
              variant="soft"
              onClick={() => service.resumeRun(run.id)}
            >
              <Play size={12} /> Resume
            </Button>
          )}
          {isLive && (
            <Button
              size="1"
              variant="soft"
              color="red"
              onClick={() => service.stopRun(run.id)}
            >
              <StopCircle size={12} /> Stop
            </Button>
          )}
          {!isLive && (
            <Button size="1" variant="soft" onClick={onNewRun}>
              <Plus size={12} /> New run
            </Button>
          )}
        </Flex>
      </Flex>
      {isSplit && (
        <Text size="1" color="gray">
          Stages: build{" "}
          {stageText(
            run.config.implementModel,
            run.config.implementEffort,
            modelOptions,
            effortOptions,
          )}{" "}
          → measure{" "}
          {stageText(
            run.config.measureModel,
            run.config.measureEffort,
            modelOptions,
            effortOptions,
          )}
        </Text>
      )}
      {run.status === "running" && liveModel && (
        <Text size="1" color="blue">
          Agent is on {stageValueLabel(liveModel, modelOptions) ?? liveModel}
          {liveEffort
            ? ` · ${stageValueLabel(liveEffort, effortOptions) ?? liveEffort} effort`
            : ""}
          {isSplit && run.phase ? ` (${run.phase} phase)` : ""}
        </Text>
      )}
      {run.status === "interrupted" && (
        <Text size="1" color="orange">
          {INTERRUPTION_LABEL[run.interruptedReason ?? ""] ??
            "Loop interrupted"}
          {run.lastError ? `. ${run.lastError}` : ""}. Resumes automatically;
          Resume retries now.
        </Text>
      )}
      {run.endReason && (
        <Text size="1" color="gray">
          {END_REASON_LABEL[run.endReason] ?? run.endReason}
          {run.lastError ? `. ${run.lastError}` : ""}
        </Text>
      )}
    </Flex>
  );
}

/**
 * An unattended loop stalls silently when the agent sits on a tool-approval
 * request; say so instead of looking idle.
 */
function PendingPermissionNotice({
  taskId,
  run,
}: {
  taskId: string;
  run: AutoresearchRun;
}) {
  const pendingPermissions = usePendingPermissionsForTask(taskId);
  const waiting =
    (run.status === "running" || run.status === "interrupted") &&
    pendingPermissions.size > 0;
  if (!waiting) return null;

  return (
    <Callout.Root color="amber" size="1">
      <Callout.Text>
        The agent is waiting for a tool approval in the chat. The loop continues
        once you respond.
      </Callout.Text>
    </Callout.Root>
  );
}

export function RunStats({ run }: { run: AutoresearchRun }) {
  const summary = useMemo(() => summarizeRun(run), [run]);
  const unit = run.metricUnit;
  const formatMetricValue = (value: number) =>
    Number.isNaN(value)
      ? "Not available"
      : withMetricUnit(metricNumberFormat.format(value), unit);
  const cardClassName = "rounded-md border border-(--gray-5) p-3";

  return (
    <div className="grid @min-[360px]:grid-cols-2 @min-[700px]:grid-cols-4 grid-cols-1 gap-2">
      <MetricCard
        title="Best"
        value={summary.best?.value ?? Number.NaN}
        formatValue={formatMetricValue}
        change={null}
        subtitle={summary.best ? `iter ${summary.best.index}` : undefined}
        className={cardClassName}
        dataAttr="autoresearch-stat-best"
      />
      <MetricCard
        title="Last"
        value={summary.last?.value ?? Number.NaN}
        formatValue={formatMetricValue}
        change={null}
        className={cardClassName}
        dataAttr="autoresearch-stat-last"
      />
      <MetricCard
        title="Iterations"
        value={summary.iterationCount}
        formatValue={(value) => `${value} / ${run.config.maxIterations}`}
        change={null}
        className={cardClassName}
        dataAttr="autoresearch-stat-iterations"
      />
      <MetricCard
        title="Target"
        value={run.config.targetValue ?? Number.NaN}
        formatValue={formatMetricValue}
        change={null}
        className={cardClassName}
        dataAttr="autoresearch-stat-target"
      />
    </div>
  );
}

export function RunSummary({ run }: { run: AutoresearchRun }) {
  const summary = summarizeRun(run);
  const bestIteration = run.iterations.find(
    (iteration) => iteration.index === summary.best?.index,
  );
  const approaches = Array.from(
    new Set(
      run.iterations.flatMap((iteration) =>
        iteration.approach ? [iteration.approach] : [],
      ),
    ),
  );
  return (
    <section className="rounded-md border border-gray-5 bg-gray-2 p-3">
      <Text as="div" size="2" weight="medium">
        Run summary
      </Text>
      <Text as="p" size="2" className="mt-2 leading-5">
        {summary.best
          ? `Best result was iteration ${summary.best.index} at ${withMetricUnit(metricNumberFormat.format(summary.best.value), run.metricUnit)}.`
          : "The run ended without a metric result."}
        {summary.improvementFromBaseline !== null
          ? ` Change from baseline: ${withMetricUnit(metricNumberFormat.format(summary.improvementFromBaseline), run.metricUnit)}.`
          : ""}
      </Text>
      {bestIteration?.hypothesis && (
        <Text as="p" size="1" color="gray" className="mt-2 leading-4">
          Best hypothesis: {bestIteration.hypothesis}
        </Text>
      )}
      {approaches.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {approaches.map((approach) => (
            <Badge key={approach} color="gray" variant="soft">
              {approach}
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}

function stageText(
  model: string | null,
  effort: string | null,
  modelOptions: AutoresearchModelOption[],
  effortOptions: AutoresearchModelOption[],
): string {
  const modelLabel = stageValueLabel(model, modelOptions) ?? "session model";
  const effortLabel = stageValueLabel(effort, effortOptions);
  return effortLabel ? `${modelLabel} · ${effortLabel}` : modelLabel;
}
