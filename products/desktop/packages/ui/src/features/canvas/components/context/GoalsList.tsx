import {
  ChartBarIcon,
  PlusIcon,
  SparkleIcon,
  StarIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  type ContextGoal,
  formatNumber,
  type GoalStatus,
  type GoalTarget,
  goalStatus,
  goalValueSuffix,
} from "@posthog/core/canvas/contextDocument";
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import {
  statusColor,
  useGoalPalette,
} from "@posthog/ui/features/canvas/goalColors";
import type { GoalMeasureTask } from "@posthog/ui/features/canvas/goalMeasureTasks";
import {
  useGoalMeasure,
  useGoalTrend,
} from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { type ReactNode, useState } from "react";
import { GoalComposer } from "./GoalComposer";
import { GoalTrendChart } from "./GoalTrendChart";
import { SectionHeader } from "./SectionHeader";

interface GoalsListProps {
  goals: ContextGoal[];
  onChange: (goals: ContextGoal[]) => Promise<void>;
  onAskAgentForMeasure: (goal: ContextGoal) => Promise<void>;
  measureTasks: ReadonlyMap<string, GoalMeasureTask>;
  onOpenMeasureTask: (taskId: string) => void;
  isSaving: boolean;
}

const GOAL_GRID = "grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4";

export function GoalsList({
  goals,
  onChange,
  onAskAgentForMeasure,
  measureTasks,
  onOpenMeasureTask,
  isSaving,
}: GoalsListProps) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const editingIndex = typeof editing === "number" ? editing : null;
  const editingGoal = editingIndex === null ? null : goals[editingIndex];

  const save = async (goal: ContextGoal) => {
    const adding = editingIndex === null;
    const primary = goal.primary || (adding && goals.length === 0);
    const next = { ...goal, primary };
    const rest = primary ? goals.map((g) => ({ ...g, primary: false })) : goals;
    const replaced = rest.map((g, i) => (i === editingIndex ? next : g));
    await onChange(adding ? [...rest, next] : replaced);
    setEditing(null);
  };
  const makePrimary = (index: number) =>
    onChange(goals.map((g, i) => ({ ...g, primary: i === index })));
  const ordered = goals
    .map((goal, index) => ({ goal, index }))
    .sort((a, b) => Number(b.goal.primary) - Number(a.goal.primary));

  const askAgent = async (goal: ContextGoal) => {
    await save(goal);
    await onAskAgentForMeasure(goal);
  };

  const remove = async () => {
    if (editingIndex === null) return;
    await onChange(goals.filter((_, i) => i !== editingIndex));
    setEditing(null);
  };

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader
        label="Goals"
        action={
          <Button
            variant="link-muted"
            size="xs"
            disabled={isSaving}
            onClick={() => setEditing("new")}
          >
            <PlusIcon size={12} />
            Add goal…
          </Button>
        }
      />

      {goals.length > 0 ? (
        <ul className={GOAL_GRID}>
          {ordered.map(({ goal, index }) => (
            <li key={`${goal.name}-${index}`} className="min-w-0">
              <GoalCard
                goal={goal}
                selected={editing === index}
                measureTask={measureTasks.get(goal.name) ?? null}
                onOpen={() => setEditing(index)}
                onOpenTask={onOpenMeasureTask}
                onRetry={() => onAskAgentForMeasure(goal)}
                onMakePrimary={
                  goal.primary ? undefined : () => makePrimary(index)
                }
                disabled={isSaving}
              />
            </li>
          ))}
        </ul>
      ) : (
        <div className={GOAL_GRID}>
          <button
            type="button"
            onClick={() => setEditing("new")}
            disabled={isSaving}
            className="flex flex-col items-start gap-1 rounded-lg border border-border border-dashed p-4 text-left transition-colors hover:bg-fill-hover"
          >
            <Text size="sm" weight="medium">
              No goals yet.
            </Text>
            <Text size="xs" variant="muted">
              Say one in a sentence. An agent writes the query.
            </Text>
          </button>
        </div>
      )}

      {editing !== null ? (
        <Dialog open onOpenChange={(open) => !open && setEditing(null)}>
          <DialogContent className="w-[640px] max-w-[92vw]">
            <DialogHeader>
              <DialogTitle>
                {editingGoal ? "Edit goal" : "New goal"}
              </DialogTitle>
              <DialogDescription>
                {editingGoal
                  ? "Change the name, the query, or the target. Agents read the saved version."
                  : "Say what should move, how far, and by when."}
              </DialogDescription>
            </DialogHeader>
            <GoalComposer
              key={editing}
              initial={editingGoal}
              takenNames={goals
                .filter((_, i) => i !== editingIndex)
                .map((goal) => goal.name)}
              onSave={save}
              onAskAgent={askAgent}
              onDelete={editingGoal ? remove : undefined}
              onClose={() => setEditing(null)}
              isSaving={isSaving}
              measureTask={
                editingGoal
                  ? (measureTasks.get(editingGoal.name) ?? null)
                  : null
              }
              onOpenTask={onOpenMeasureTask}
              onRetryMeasure={
                editingGoal
                  ? async () => {
                      setEditing(null);
                      await onAskAgentForMeasure(editingGoal);
                    }
                  : undefined
              }
            />
          </DialogContent>
        </Dialog>
      ) : null}
    </section>
  );
}

const STATUS_LABEL: Record<GoalStatus, string> = {
  met: "Met",
  on_track: "On track",
  behind: "Behind",
  no_target: "No target",
  unmeasured: "Not measured",
};

function describeTarget(target: GoalTarget): string {
  const sign = target.direction === "at_most" ? "≤" : "≥";
  const due = target.dueDate ? ` by ${formatDueDate(target.dueDate)}` : "";
  return `${sign} ${formatNumber(target.value)}${due}`;
}

function formatDueDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function GoalCard({
  goal,
  selected,
  measureTask,
  onOpen,
  onOpenTask,
  onRetry,
  onMakePrimary,
  disabled,
}: {
  goal: ContextGoal;
  selected: boolean;
  measureTask: GoalMeasureTask | null;
  onOpen: () => void;
  onOpenTask: (taskId: string) => void;
  onRetry: () => Promise<void>;
  onMakePrimary?: () => Promise<void>;
  disabled: boolean;
}) {
  const measure = useGoalMeasure(goal.measure);
  const trend = useGoalTrend(goal.name, goal.measure);
  const agentState: AgentState | null =
    goal.measure === null ? (measureTask?.state ?? "waiting") : null;

  return (
    <div
      className={cn(
        "group/card relative flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-background transition-colors hover:border-muted-foreground/50",
        selected && "border-muted-foreground",
      )}
    >
      {onMakePrimary ? (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Make primary"
          disabled={disabled}
          onClick={() => void onMakePrimary()}
          className="absolute top-3 right-3 z-10 opacity-0 transition-opacity focus-visible:opacity-100 group-hover/card:opacity-100"
        >
          <StarIcon size={13} />
        </Button>
      ) : null}
      <button
        type="button"
        onClick={onOpen}
        disabled={disabled}
        aria-pressed={selected}
        className="flex flex-col gap-4 p-4 text-left"
      >
        <span className="flex min-w-0 flex-col gap-0.5">
          <span
            className={cn(
              "flex items-center gap-1.5 font-medium text-foreground text-sm",
              onMakePrimary && "pr-7",
            )}
          >
            {goal.measure?.kind === "insight" ? (
              <ChartBarIcon
                size={13}
                className="shrink-0 text-muted-foreground"
              />
            ) : null}
            <span className="truncate">{goal.name}</span>
            {goal.primary ? (
              <span className="ml-auto flex shrink-0 items-center gap-1 font-normal text-muted-foreground text-xs">
                <StarIcon size={12} weight="fill" />
                Primary
              </span>
            ) : null}
          </span>
          {goal.why ? (
            <span className="line-clamp-1 text-muted-foreground text-xs">
              {goal.why}
            </span>
          ) : null}
        </span>
        <span className="flex items-end justify-between gap-3">
          <span className="font-semibold text-2xl text-foreground tabular-nums leading-none">
            <CurrentValue
              value={measure.data ?? null}
              loading={measure.isLoading}
              unit={goalValueSuffix(goal.name)}
            />
          </span>
          <MeasureStatus
            goal={goal}
            current={measure.data ?? null}
            failed={measure.error !== null}
            agentState={agentState}
          />
        </span>
      </button>
      <div className="mt-auto flex h-16 items-center justify-center">
        <CardFooter
          goal={goal}
          trend={trend}
          endedTask={agentState === "ended" ? measureTask : null}
          disabled={disabled}
          onOpenTask={onOpenTask}
          onRetry={onRetry}
        />
      </div>
    </div>
  );
}

type AgentState = GoalMeasureTask["state"] | "waiting";

function CurrentValue({
  value,
  loading,
  unit,
}: {
  value: number | null;
  loading: boolean;
  unit: string;
}) {
  if (value !== null) {
    return (
      <>
        {formatNumber(value)}
        {unit}
      </>
    );
  }
  if (loading) return <Spinner size="xs" aria-hidden="true" />;
  return <span className="text-muted-foreground">–</span>;
}

const AGENT_STATUS: Record<AgentState, { icon: ReactNode; text: string }> = {
  waiting: {
    icon: <SparkleIcon size={13} className="shrink-0" />,
    text: "Waiting for a measure",
  },
  running: {
    icon: <Spinner size="xs" aria-hidden="true" />,
    text: "Agent writing the measure",
  },
  ended: {
    icon: (
      <WarningCircleIcon
        size={13}
        className="shrink-0 text-warning-foreground"
      />
    ),
    text: "No measure came back",
  },
};

function MeasureStatus({
  goal,
  current,
  failed,
  agentState,
}: {
  goal: ContextGoal;
  current: number | null;
  failed: boolean;
  agentState: AgentState | null;
}) {
  const palette = useGoalPalette();
  if (agentState) {
    const { icon, text } = AGENT_STATUS[agentState];
    return (
      <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
        {icon}
        {text}
      </span>
    );
  }
  if (failed) {
    return (
      <span className="flex items-center gap-1.5 text-warning-foreground text-xs">
        <WarningCircleIcon size={13} className="shrink-0" />
        Query failed
      </span>
    );
  }
  const status = goalStatus(current, goal.target);
  const detail = goal.target
    ? `${STATUS_LABEL[status]} · ${describeTarget(goal.target)}`
    : STATUS_LABEL[status];
  return (
    <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: statusColor(status, palette) }}
      />
      {detail}
    </span>
  );
}

function CardFooter({
  goal,
  trend,
  endedTask,
  disabled,
  onOpenTask,
  onRetry,
}: {
  goal: ContextGoal;
  trend: ReturnType<typeof useGoalTrend>;
  endedTask: GoalMeasureTask | null;
  disabled: boolean;
  onOpenTask: (taskId: string) => void;
  onRetry: () => Promise<void>;
}) {
  const points = trend.data?.points ?? [];
  if (points.length > 1) {
    return (
      <div className="h-full w-full">
        <GoalTrendChart
          points={points}
          period={trend.data?.period ?? "day"}
          target={goal.target}
          unit={goalValueSuffix(goal.name)}
        />
      </div>
    );
  }
  if (trend.isLoading) return <Spinner size="xs" aria-hidden="true" />;
  if (!endedTask) return null;
  return (
    <span className="flex items-center gap-1">
      <Button
        variant="link-muted"
        size="xs"
        onClick={() => onOpenTask(endedTask.taskId)}
      >
        Open task
      </Button>
      <Button
        variant="link-muted"
        size="xs"
        disabled={disabled}
        onClick={() => void onRetry()}
      >
        Try again
      </Button>
    </span>
  );
}
