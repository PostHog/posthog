import {
  ArrowsClockwiseIcon,
  PencilSimpleIcon,
  PlusIcon,
  TargetIcon,
  TrashIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  type ContextGoal,
  formatNumber,
  type GoalDirection,
  type GoalStatus,
  goalProgress,
  goalStatus,
} from "@posthog/core/canvas/contextDocument";
import {
  Badge,
  Button,
  cn,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useGoalMeasure } from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";
import { GoalDialog } from "./GoalDialog";
import { SectionCard, SectionPlaceholder } from "./SectionCard";

interface GoalsSectionProps {
  goals: ContextGoal[];
  onChange: (goals: ContextGoal[]) => Promise<void>;
  isSaving: boolean;
}

type Editing = { index: number | null } | null;

/** The numbers this space is trying to move, each backed by a HogQL measure. */
export function GoalsSection({ goals, onChange, isSaving }: GoalsSectionProps) {
  const [editing, setEditing] = useState<Editing>(null);

  const upsert = async (goal: ContextGoal) => {
    if (editing?.index === null || editing === null) {
      await onChange([...goals, goal]);
    } else {
      await onChange(goals.map((g, i) => (i === editing.index ? goal : g)));
    }
    setEditing(null);
  };

  const remove = (index: number) =>
    onChange(goals.filter((_, i) => i !== index));

  return (
    <SectionCard
      icon={<TargetIcon size={16} />}
      title="Goals"
      description="The numbers this space moves. Each goal has a HogQL measure, a target, and the reason it matters."
      count={goals.length}
      flush
      actions={
        goals.length > 0 ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing({ index: null })}
          >
            <PlusIcon size={14} />
            Add goal
          </Button>
        ) : null
      }
    >
      {goals.length > 0 ? (
        <ul className="grid @2xl:grid-cols-2 gap-3">
          {goals.map((goal, index) => (
            <li key={`${goal.name}-${index}`}>
              <GoalCard
                goal={goal}
                onEdit={() => setEditing({ index })}
                onRemove={() => void remove(index)}
                disabled={isSaving}
              />
            </li>
          ))}
        </ul>
      ) : (
        <div className="rounded-lg border border-border border-dashed bg-card">
          <SectionPlaceholder>
            <Text size="xs" weight="medium">
              No goals yet
            </Text>
            <Text size="xs" variant="muted" className="max-w-[440px]">
              A goal is a HogQL query that returns one number, a target for it,
              and why it matters. Agents use goals to report progress and to
              propose bets.
            </Text>
            <Button
              variant="primary"
              size="sm"
              className="mt-2"
              onClick={() => setEditing({ index: null })}
            >
              <PlusIcon size={14} />
              Add a goal
            </Button>
          </SectionPlaceholder>
        </div>
      )}

      <GoalDialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        initial={
          editing && editing.index !== null ? goals[editing.index] : null
        }
        onSubmit={upsert}
        isSaving={isSaving}
      />
    </SectionCard>
  );
}

const STATUS_BADGE: Record<
  GoalStatus,
  { label: string; variant: "success" | "info" | "warning" | "default" }
> = {
  met: { label: "Met", variant: "success" },
  on_track: { label: "On track", variant: "info" },
  behind: { label: "Behind", variant: "warning" },
  no_target: { label: "No target", variant: "default" },
  unmeasured: { label: "Not measured", variant: "default" },
};

function describeTarget(
  direction: GoalDirection,
  value: number,
  dueDate: string | null,
): string {
  const word = direction === "at_most" ? "at most" : "at least";
  const due = dueDate ? ` by ${formatDueDate(dueDate)}` : "";
  return `Target ${word} ${formatNumber(value)}${due}`;
}

function formatDueDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function GoalCard({
  goal,
  onEdit,
  onRemove,
  disabled,
}: {
  goal: ContextGoal;
  onEdit: () => void;
  onRemove: () => void;
  disabled: boolean;
}) {
  const measure = useGoalMeasure(goal.sql);
  const current = measure.data ?? null;
  const status = goalStatus(current, goal.target);
  const progress =
    goal.target && current !== null ? goalProgress(current, goal.target) : 0;
  const badge = STATUS_BADGE[status];

  return (
    <article className="group/goal flex h-full flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <Text size="sm" weight="semibold" className="truncate">
            {goal.name}
          </Text>
          {goal.why ? (
            <Text size="xs" variant="muted" className="line-clamp-2">
              {goal.why}
            </Text>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-focus-within/goal:opacity-100 group-hover/goal:opacity-100">
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-xs"
                    aria-label="Refresh measure"
                    disabled={measure.isFetching || !goal.sql}
                    onClick={() => void measure.refetch()}
                  />
                }
              >
                <ArrowsClockwiseIcon size={14} />
              </TooltipTrigger>
              <TooltipContent>Run the measure again</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-xs"
                    aria-label="Edit goal"
                    disabled={disabled}
                    onClick={onEdit}
                  />
                }
              >
                <PencilSimpleIcon size={14} />
              </TooltipTrigger>
              <TooltipContent>Edit</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-xs"
                    aria-label="Remove goal"
                    disabled={disabled}
                    onClick={onRemove}
                  />
                }
              >
                <TrashIcon size={14} />
              </TooltipTrigger>
              <TooltipContent>Remove</TooltipContent>
            </Tooltip>
          </div>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </header>

      <div className="flex items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <span className="font-semibold text-2xl text-foreground tabular-nums leading-none">
            {measure.isLoading ? (
              <Spinner size="sm" aria-hidden="true" />
            ) : measure.error ? (
              <span className="flex items-center gap-1 text-warning-foreground">
                <WarningCircleIcon size={18} />
                <span className="text-sm">Query failed</span>
              </span>
            ) : current === null ? (
              <span className="text-muted-foreground">—</span>
            ) : (
              formatNumber(current)
            )}
          </span>
          {goal.target ? (
            <Text size="xxs" variant="muted" className="mt-1">
              {describeTarget(
                goal.target.direction,
                goal.target.value,
                goal.target.dueDate,
              )}
            </Text>
          ) : (
            <Text size="xxs" variant="muted" className="mt-1">
              Current value
            </Text>
          )}
        </div>
      </div>

      {goal.target ? (
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-500",
              status === "met" && "bg-success-foreground",
              status === "on_track" && "bg-info-foreground",
              status === "behind" && "bg-warning-foreground",
              (status === "no_target" || status === "unmeasured") &&
                "bg-muted-foreground/40",
            )}
            style={{ width: `${Math.max(2, Math.round(progress * 100))}%` }}
          />
        </div>
      ) : null}

      {measure.error ? (
        <Text size="xxs" className="text-warning-foreground">
          {measure.error.message}
        </Text>
      ) : null}

      {goal.sql ? (
        <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted px-3 py-2 font-mono text-[11px] text-muted-foreground leading-relaxed">
          {goal.sql}
        </pre>
      ) : (
        <Text size="xxs" variant="muted">
          No measure yet. Edit the goal to add a HogQL query.
        </Text>
      )}
    </article>
  );
}
