import {
  ChartBarIcon,
  PlusIcon,
  SparkleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  type ContextGoal,
  formatNumber,
  type GoalStatus,
  type GoalTarget,
  goalProgress,
  goalStatus,
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
import { Sparkline, useChartTheme } from "@posthog/quill-charts";
import type { GoalMeasureTask } from "@posthog/ui/features/canvas/goalMeasureTasks";
import { goalValueSuffix } from "@posthog/ui/features/canvas/goalUnits";
import {
  useGoalMeasure,
  useGoalTrend,
} from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";
import { GoalComposer } from "./GoalComposer";
import { SectionHeader } from "./SectionHeader";

interface GoalsListProps {
  goals: ContextGoal[];
  onChange: (goals: ContextGoal[]) => Promise<void>;
  /** Start a task that writes a measure for a goal saved without one. */
  onAskAgentForMeasure: (goal: ContextGoal) => Promise<void>;
  /** The agent task behind each goal that has no measure yet, by goal name. */
  measureTasks: ReadonlyMap<string, GoalMeasureTask>;
  /** The agent task writing a trend for a measured goal that has none, by goal name. */
  trendTasks: ReadonlyMap<string, GoalMeasureTask>;
  onAskAgentForTrend: (goal: ContextGoal) => Promise<void>;
  onOpenMeasureTask: (taskId: string) => void;
  isSaving: boolean;
}

type Editing = { index: number | null } | null;

/**
 * The numbers this space moves, as rows at the top of the document. A row
 * opens the goal in a dialog, where removal lives too, so the list never
 * changes shape while someone is writing.
 */
export function GoalsList({
  goals,
  onChange,
  onAskAgentForMeasure,
  measureTasks,
  trendTasks,
  onAskAgentForTrend,
  onOpenMeasureTask,
  isSaving,
}: GoalsListProps) {
  const [editing, setEditing] = useState<Editing>(null);
  const editingGoal =
    editing && editing.index !== null ? goals[editing.index] : null;

  const save = async (goal: ContextGoal) => {
    if (editing?.index == null) {
      await onChange([...goals, goal]);
    } else {
      await onChange(goals.map((g, i) => (i === editing.index ? goal : g)));
    }
    setEditing(null);
  };

  const askAgent = async (goal: ContextGoal) => {
    await save(goal);
    await onAskAgentForMeasure(goal);
  };

  const remove = async () => {
    if (editing?.index == null) return;
    await onChange(goals.filter((_, i) => i !== editing.index));
    setEditing(null);
  };

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader
        label="Goals"
        action={
          <Button
            variant="link-muted"
            size="xs"
            disabled={isSaving}
            onClick={() => setEditing({ index: null })}
          >
            <PlusIcon size={12} />
            Add goal…
          </Button>
        }
      />

      {goals.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border border-border border-y">
          {goals.map((goal, index) => (
            <li key={`${goal.name}-${index}`}>
              <GoalRow
                goal={goal}
                selected={editing?.index === index}
                measureTask={measureTasks.get(goal.name) ?? null}
                trendTask={trendTasks.get(goal.name) ?? null}
                onOpen={() => setEditing({ index })}
                onOpenTask={onOpenMeasureTask}
                onRetry={() => onAskAgentForMeasure(goal)}
                onAskTrend={() => onAskAgentForTrend(goal)}
                disabled={isSaving}
              />
            </li>
          ))}
        </ul>
      ) : (
        <button
          type="button"
          onClick={() => setEditing({ index: null })}
          disabled={isSaving}
          className="flex items-baseline gap-2 border-border border-y py-4 text-left transition-colors hover:bg-fill-hover"
        >
          <Text size="sm" weight="medium">
            No goals yet.
          </Text>
          <Text size="xs" variant="muted">
            Say one in a sentence. An agent writes the query.
          </Text>
        </button>
      )}

      {editing ? (
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
              key={editing.index ?? "new"}
              initial={editingGoal}
              takenNames={goals
                .filter((_, i) => i !== editing.index)
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

const STATUS_DOT: Record<GoalStatus, string> = {
  met: "bg-success-foreground",
  on_track: "bg-info-foreground",
  behind: "bg-warning-foreground",
  no_target: "bg-muted-foreground/50",
  unmeasured: "bg-muted-foreground/50",
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

function GoalRow({
  goal,
  selected,
  measureTask,
  trendTask,
  onOpen,
  onOpenTask,
  onRetry,
  onAskTrend,
  disabled,
}: {
  goal: ContextGoal;
  selected: boolean;
  measureTask: GoalMeasureTask | null;
  trendTask: GoalMeasureTask | null;
  onOpen: () => void;
  onOpenTask: (taskId: string) => void;
  onRetry: () => Promise<void>;
  onAskTrend: () => Promise<void>;
  disabled: boolean;
}) {
  const measure = useGoalMeasure(goal.measure);
  const trend = useGoalTrend(goal.measure);
  const theme = useChartTheme();
  const current = measure.data ?? null;
  const status = goalStatus(current, goal.target);
  const measured = current !== null;
  const progress =
    goal.target && measured ? goalProgress(current, goal.target) : 0;
  const detail = goal.target
    ? `${STATUS_LABEL[status]} · ${describeTarget(goal.target)}`
    : STATUS_LABEL[status];
  const agentRunning =
    goal.measure === null && measureTask?.state === "running";
  const agentEnded = goal.measure === null && measureTask?.state === "ended";
  const hasTrendQuery =
    goal.measure?.kind === "hogql" && Boolean(goal.measure.trendSql?.trim());
  const canAskTrend =
    goal.measure?.kind === "hogql" && !hasTrendQuery && trendTask === null;
  const points = trend.data ?? [];

  return (
    <div
      className={cn(
        "-mx-3 grid w-[calc(100%+1.5rem)] grid-cols-[minmax(12rem,1fr)_minmax(0,2fr)_minmax(10rem,auto)] items-center gap-8 rounded-md px-3 transition-colors hover:bg-fill-hover",
        selected && "bg-fill-selected",
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        disabled={disabled}
        aria-pressed={selected}
        className="flex min-w-0 flex-col gap-0.5 py-4 text-left"
      >
        <span className="flex items-center gap-1.5 font-medium text-foreground text-sm">
          {goal.measure?.kind === "insight" ? (
            <ChartBarIcon
              size={13}
              className="shrink-0 text-muted-foreground"
            />
          ) : null}
          <span className="truncate">{goal.name}</span>
        </span>
        {goal.why ? (
          <span className="truncate text-muted-foreground text-xs">
            {goal.why}
          </span>
        ) : null}
      </button>

      <div className="flex h-10 min-w-0 items-center">
        {points.length > 1 ? (
          <div className="h-10 w-full">
            <Sparkline data={points} theme={theme} height={40} />
          </div>
        ) : agentEnded && measureTask ? (
          <span className="flex items-center gap-1">
            <Button
              variant="link-muted"
              size="xs"
              onClick={() => onOpenTask(measureTask.taskId)}
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
        ) : trendTask?.state === "running" ? (
          <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
            <Spinner size="xs" aria-hidden="true" />
            An agent is writing the trend
          </span>
        ) : trendTask?.state === "ended" ? (
          <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
            <WarningCircleIcon
              size={13}
              className="shrink-0 text-warning-foreground"
            />
            The agent finished without a trend
            <Button
              variant="link-muted"
              size="xs"
              disabled={disabled}
              onClick={() => void onAskTrend()}
            >
              Try again
            </Button>
          </span>
        ) : (
          <span className="flex w-full items-center gap-3">
            <span className="h-px flex-1 border-border border-t border-dashed" />
            {canAskTrend ? (
              <Button
                variant="link-muted"
                size="xs"
                disabled={disabled}
                onClick={() => void onAskTrend()}
              >
                <SparkleIcon size={12} />
                Add trend
              </Button>
            ) : null}
            <span className="h-px flex-1 border-border border-t border-dashed" />
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={onOpen}
        disabled={disabled}
        tabIndex={-1}
        className="flex min-w-0 flex-col items-end gap-1.5 py-4 text-right"
      >
        {measured ? (
          <span className="font-semibold text-foreground text-xl tabular-nums leading-none">
            {formatNumber(current)}
            {goalValueSuffix(goal.name)}
          </span>
        ) : measure.isLoading ? (
          <Spinner size="xs" aria-hidden="true" />
        ) : null}
        {goal.measure === null ? (
          <span className="flex items-center gap-1.5 whitespace-nowrap text-muted-foreground text-xs">
            {agentRunning ? (
              <Spinner size="xs" aria-hidden="true" />
            ) : agentEnded ? (
              <WarningCircleIcon
                size={13}
                className="shrink-0 text-warning-foreground"
              />
            ) : (
              <SparkleIcon size={13} className="shrink-0" />
            )}
            {agentRunning
              ? "An agent is writing the measure"
              : agentEnded
                ? "The agent finished without a measure"
                : "Waiting for a measure"}
          </span>
        ) : measure.error ? (
          <span className="flex items-center gap-1.5 whitespace-nowrap text-warning-foreground text-xs">
            <WarningCircleIcon size={13} className="shrink-0" />
            Query failed
          </span>
        ) : (
          <span className="flex items-center gap-1.5 whitespace-nowrap text-muted-foreground text-xs">
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                STATUS_DOT[status],
              )}
            />
            {detail}
          </span>
        )}
        {goal.target && measured ? (
          <span
            className="h-1 w-full overflow-hidden rounded-full bg-border"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
          >
            <span
              className={cn("block h-full rounded-full", STATUS_DOT[status])}
              style={{
                width: `${progress > 0 ? Math.max(2, Math.round(progress * 100)) : 0}%`,
              }}
            />
          </span>
        ) : null}
      </button>
    </div>
  );
}
