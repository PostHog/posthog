import { PlayIcon } from "@phosphor-icons/react";
import {
  type ContextGoal,
  firstNumericCell,
  formatNumber,
  type GoalDirection,
} from "@posthog/core/canvas/contextDocument";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldDescription,
  FieldLabel,
  Input,
  Text,
  Textarea,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

interface GoalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The goal being edited, or null for a new one. */
  initial: ContextGoal | null;
  onSubmit: (goal: ContextGoal) => Promise<void>;
  isSaving: boolean;
}

const SQL_PLACEHOLDER = `SELECT count(DISTINCT person_id)
FROM events
WHERE event = 'signed_up'
  AND timestamp >= now() - INTERVAL 7 DAY`;

const DIRECTION_OPTIONS = [
  { value: "at_least", label: "At least" },
  { value: "at_most", label: "At most" },
];

/** Create or edit one goal: name, why, HogQL measure, and target. */
export function GoalDialog({
  open,
  onOpenChange,
  initial,
  onSubmit,
  isSaving,
}: GoalDialogProps) {
  const [name, setName] = useState("");
  const [why, setWhy] = useState("");
  const [sql, setSql] = useState("");
  const [direction, setDirection] = useState<GoalDirection>("at_least");
  const [targetValue, setTargetValue] = useState("");
  const [dueDate, setDueDate] = useState("");

  const client = useOptionalAuthenticatedClient();
  const testRun = useMutation({
    mutationFn: async (query: string) => {
      if (!client) throw new Error("Not authenticated");
      const grid = await client.runHogQLQuery(query);
      return {
        value: firstNumericCell(grid.results),
        columns: grid.columns,
        rows: grid.results.length,
      };
    },
  });
  const resetTestRun = testRun.reset;

  // Reset the form each time the dialog opens, from the goal being edited or
  // blank for a new one.
  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setWhy(initial?.why ?? "");
    setSql(initial?.sql ?? "");
    setDirection(initial?.target?.direction ?? "at_least");
    setTargetValue(initial?.target ? String(initial.target.value) : "");
    setDueDate(initial?.target?.dueDate ?? "");
    resetTestRun();
  }, [open, initial, resetTestRun]);

  const parsedTarget = targetValue.trim()
    ? Number(targetValue.replace(/,/g, ""))
    : null;
  const targetInvalid = parsedTarget !== null && !Number.isFinite(parsedTarget);
  const canSave = name.trim().length > 0 && !targetInvalid && !isSaving;

  const submit = async () => {
    if (!canSave) return;
    await onSubmit({
      name: name.trim(),
      why: why.trim(),
      sql: sql.trim(),
      target:
        parsedTarget !== null && Number.isFinite(parsedTarget)
          ? { direction, value: parsedTarget, dueDate: dueDate || null }
          : null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{initial ? "Edit goal" : "New goal"}</DialogTitle>
          <DialogDescription>
            One number, one target, and the reason it matters. Agents read all
            three.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex max-h-[65vh] flex-col gap-4">
          <Field>
            <FieldLabel htmlFor="goal-name">Name</FieldLabel>
            <Input
              id="goal-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Weekly activated teams"
              disabled={isSaving}
            />
          </Field>

          <Field>
            <FieldLabel htmlFor="goal-why">Why it matters</FieldLabel>
            <Textarea
              id="goal-why"
              value={why}
              onChange={(e) => setWhy(e.target.value)}
              placeholder="What this number tells us, and what moves it."
              disabled={isSaving}
              className="min-h-[64px] resize-y text-xs"
            />
          </Field>

          <Field>
            <div className="flex items-center justify-between gap-2">
              <FieldLabel htmlFor="goal-sql">Measure (HogQL)</FieldLabel>
              <Button
                type="button"
                variant="outline"
                size="xs"
                disabled={!sql.trim() || testRun.isPending}
                onClick={() => testRun.mutate(sql)}
              >
                {testRun.isPending ? <Spinner /> : <PlayIcon size={12} />}
                Run
              </Button>
            </div>
            <Textarea
              id="goal-sql"
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              placeholder={SQL_PLACEHOLDER}
              disabled={isSaving}
              spellCheck={false}
              className="min-h-[120px] resize-y font-mono text-xs leading-relaxed"
            />
            <FieldDescription>
              The first cell of the first row is the current value.
            </FieldDescription>
            {testRun.isSuccess ? (
              <div className="flex items-center justify-between gap-3 rounded-md bg-muted px-3 py-2">
                <Text size="xs" variant="muted">
                  {testRun.data.rows === 0
                    ? "The query returned no rows."
                    : testRun.data.value === null
                      ? `Returned ${testRun.data.rows} row(s), but the first row has no number.`
                      : `Current value from ${testRun.data.columns[0] ?? "the first column"}`}
                </Text>
                {testRun.data.value !== null ? (
                  <span className="font-semibold text-foreground text-lg tabular-nums">
                    {formatNumber(testRun.data.value)}
                  </span>
                ) : null}
              </div>
            ) : null}
            {testRun.error ? (
              <Text size="xs" className="text-destructive">
                {testRun.error.message}
              </Text>
            ) : null}
          </Field>

          <Field>
            <FieldLabel htmlFor="goal-target">Target</FieldLabel>
            <div className="grid gap-2 sm:grid-cols-[140px_minmax(0,1fr)_170px]">
              <SettingsSelect
                value={direction}
                onChange={(next) => {
                  if (next === "at_least" || next === "at_most") {
                    setDirection(next);
                  }
                }}
                options={DIRECTION_OPTIONS}
                ariaLabel="Target direction"
              />
              <Input
                id="goal-target"
                inputMode="decimal"
                value={targetValue}
                onChange={(e) => setTargetValue(e.target.value)}
                placeholder="e.g. 500"
                disabled={isSaving}
                aria-invalid={targetInvalid || undefined}
                className="tabular-nums"
              />
              <Input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                disabled={isSaving}
                aria-label="Due date"
              />
            </div>
            <FieldDescription>
              {targetInvalid
                ? "The target must be a number."
                : "Leave the target empty to track the number without a goal line."}
            </FieldDescription>
          </Field>
        </DialogBody>
        <DialogFooter>
          <DialogClose
            render={
              <Button variant="outline" disabled={isSaving}>
                Cancel
              </Button>
            }
          />
          <Button
            variant="primary"
            disabled={!canSave}
            loading={isSaving}
            onClick={() => void submit()}
          >
            {initial ? "Save goal" : "Add goal"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
