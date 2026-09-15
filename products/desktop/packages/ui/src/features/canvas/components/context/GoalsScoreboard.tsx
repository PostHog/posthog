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
import { cn, Text } from "@posthog/quill";
import { useGoalMeasure } from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";
import { GoalComposer } from "./GoalComposer";

interface GoalsScoreboardProps {
  goals: ContextGoal[];
  onChange: (goals: ContextGoal[]) => Promise<void>;
  /** Start a task that writes a measure for a goal saved without one. */
  onAskAgentForMeasure: (goal: ContextGoal) => Promise<void>;
  isSaving: boolean;
}

type Editing = { index: number | null } | null;

/**
 * The numbers this space moves, as one row of tiles above the briefing. A tile
 * opens the goal in the composer below the row; removal lives there too, so a
 * tile stays a single button.
 */
export function GoalsScoreboard({
  goals,
  onChange,
  onAskAgentForMeasure,
  isSaving,
}: GoalsScoreboardProps) {
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
      <Text size="xs" weight="medium" variant="muted">
        Goals
      </Text>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-2">
        {goals.map((goal, index) => (
          <li key={`${goal.name}-${index}`}>
            <GoalTile
              goal={goal}
              selected={editing?.index === index}
              onOpen={() => setEditing({ index })}
              disabled={isSaving}
            />
          </li>
        ))}
        {editing?.index === null ? null : (
          <li>
            <button
              type="button"
              onClick={() => setEditing({ index: null })}
              disabled={isSaving}
              className={cn(
                "flex h-full min-h-[104px] w-full flex-col items-center justify-center gap-1 rounded-lg border border-border border-dashed px-3 py-3 text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground",
                goals.length === 0 && "items-start text-left",
              )}
            >
              <span className="flex items-center gap-1.5 font-medium text-xs">
                <PlusIcon size={14} />
                {goals.length === 0 ? "Add the first goal" : "Add goal"}
              </span>
              {goals.length === 0 ? (
                <span className="text-xxs">
                  Say it in a sentence. The query and the target follow.
                </span>
              ) : null}
            </button>
          </li>
        )}
      </ul>

      {editing ? (
        <GoalComposer
          key={editing.index ?? "new"}
          initial={editingGoal}
          onSave={save}
          onAskAgent={askAgent}
          onDelete={editingGoal ? remove : undefined}
          onClose={() => setEditing(null)}
          isSaving={isSaving}
        />
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
  return `Target ${sign} ${formatNumber(target.value)}${due}`;
}

function formatDueDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function GoalTile({
  goal,
  selected,
  onOpen,
  disabled,
}: {
  goal: ContextGoal;
  selected: boolean;
  onOpen: () => void;
  disabled: boolean;
}) {
  const measure = useGoalMeasure(goal.measure);
  const current = measure.data ?? null;
  const status = goalStatus(current, goal.target);
  const progress =
    goal.target && current !== null ? goalProgress(current, goal.target) : 0;

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={disabled}
      title={goal.why || goal.name}
      aria-pressed={selected}
      className={cn(
        "flex h-full w-full flex-col gap-2 rounded-lg border bg-card px-3 py-3 text-left transition-colors hover:bg-fill-hover",
        selected ? "border-foreground/40" : "border-border",
      )}
    >
      <span className="flex items-center gap-1.5 truncate text-muted-foreground text-xs">
        {goal.measure?.kind === "insight" ? (
          <ChartBarIcon size={12} className="shrink-0" />
        ) : null}
        <span className="truncate">{goal.name}</span>
      </span>
      <span className="font-semibold text-foreground text-xl tabular-nums leading-none">
        {goal.measure === null ? (
          <span className="flex items-center gap-1.5 text-muted-foreground text-sm">
            <SparkleIcon size={14} />
            Waiting for a measure
          </span>
        ) : measure.isLoading ? (
          <Spinner size="sm" aria-hidden="true" />
        ) : measure.error ? (
          <span className="flex items-center gap-1 text-sm text-warning-foreground">
            <WarningCircleIcon size={16} />
            Query failed
          </span>
        ) : current === null ? (
          <span className="text-muted-foreground">–</span>
        ) : (
          formatNumber(current)
        )}
      </span>
      {goal.target ? (
        <span
          className="h-1 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
        >
          <span
            className={cn("block h-full rounded-full", STATUS_DOT[status])}
            style={{ width: `${Math.max(2, Math.round(progress * 100))}%` }}
          />
        </span>
      ) : null}
      <span className="flex items-center gap-1.5 text-muted-foreground text-xxs">
        <span
          className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[status])}
        />
        <span className="truncate">
          {goal.target
            ? `${STATUS_LABEL[status]} · ${describeTarget(goal.target)}`
            : STATUS_LABEL[status]}
        </span>
      </span>
    </button>
  );
}
