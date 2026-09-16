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
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { useGoalMeasure } from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";
import { GoalComposer } from "./GoalComposer";

interface GoalsListProps {
  goals: ContextGoal[];
  onChange: (goals: ContextGoal[]) => Promise<void>;
  /** Start a task that writes a measure for a goal saved without one. */
  onAskAgentForMeasure: (goal: ContextGoal) => Promise<void>;
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
    <section className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          Goals
        </Text>
        <Button
          variant="link-muted"
          size="xs"
          disabled={isSaving}
          onClick={() => setEditing({ index: null })}
        >
          <PlusIcon size={12} />
          Add goal…
        </Button>
      </div>

      {goals.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border border-border border-y">
          {goals.map((goal, index) => (
            <li key={`${goal.name}-${index}`}>
              <GoalRow
                goal={goal}
                selected={editing?.index === index}
                onOpen={() => setEditing({ index })}
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
            Say one in a sentence. The query and the target follow.
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
                  : "Say it in a sentence. The query and the target follow."}
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <GoalComposer
                key={editing.index ?? "new"}
                initial={editingGoal}
                onSave={save}
                onAskAgent={askAgent}
                onDelete={editingGoal ? remove : undefined}
                onClose={() => setEditing(null)}
                isSaving={isSaving}
              />
            </DialogBody>
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
      aria-pressed={selected}
      className={cn(
        "-mx-3 grid w-[calc(100%+1.5rem)] grid-cols-[minmax(0,1fr)_auto] items-center gap-6 rounded-md px-3 py-3 text-left transition-colors hover:bg-fill-hover",
        selected && "bg-fill-selected",
      )}
    >
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-center gap-1.5 truncate font-medium text-foreground text-sm">
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
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
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
        <span className="flex items-center gap-2 text-muted-foreground text-xxs">
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                STATUS_DOT[status],
              )}
            />
            {goal.target
              ? `${STATUS_LABEL[status]} · ${describeTarget(goal.target)}`
              : STATUS_LABEL[status]}
          </span>
          {goal.target ? (
            <span
              className="h-1 w-20 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
            >
              <span
                className={cn("block h-full rounded-full", STATUS_DOT[status])}
                style={{
                  width: `${Math.max(2, Math.round(progress * 100))}%`,
                }}
              />
            </span>
          ) : null}
        </span>
      </span>
    </button>
  );
}
