import { PlayIcon } from "@phosphor-icons/react";
import {
  type ContextGoal,
  firstNumericCell,
  formatNumber,
  type GoalDirection,
  type GoalMeasure,
  parsePostHogObjectUrl,
} from "@posthog/core/canvas/contextDocument";
import { insightCurrentValue } from "@posthog/core/canvas/goalMeasures";
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
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

type MeasureMode = "hogql" | "insight" | "agent";

export interface GoalSubmitOptions {
  /** Save the goal without a measure and start a task that writes one. */
  askAgent: boolean;
}

interface GoalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The goal being edited, or null for a new one. */
  initial: ContextGoal | null;
  onSubmit: (goal: ContextGoal, options: GoalSubmitOptions) => Promise<void>;
  /** Present when editing an existing goal. */
  onDelete?: () => Promise<void>;
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

/** Create or edit one goal: name, why, target, and how it is measured. */
export function GoalDialog({
  open,
  onOpenChange,
  initial,
  onSubmit,
  onDelete,
  isSaving,
}: GoalDialogProps) {
  const [name, setName] = useState("");
  const [why, setWhy] = useState("");
  const [mode, setMode] = useState<MeasureMode>("hogql");
  const [sql, setSql] = useState("");
  const [insightUrl, setInsightUrl] = useState("");
  const [insightName, setInsightName] = useState("");
  const [direction, setDirection] = useState<GoalDirection>("at_least");
  const [targetValue, setTargetValue] = useState("");
  const [dueDate, setDueDate] = useState("");

  const client = useOptionalAuthenticatedClient();
  const sqlRun = useMutation({
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
  const insightRun = useMutation({
    mutationFn: async (shortId: string) => {
      if (!client) throw new Error("Not authenticated");
      const insight = await client.getInsightDefinition(shortId);
      if (!insight) throw new Error("No insight with that id in this project.");
      return {
        name: insight.name ?? shortId,
        value: insightCurrentValue(insight.response?.results),
      };
    },
    onSuccess: (data) => {
      if (!insightName.trim()) setInsightName(data.name);
    },
  });
  const resetSqlRun = sqlRun.reset;
  const resetInsightRun = insightRun.reset;

  // Reset the form each time the dialog opens, from the goal being edited or
  // blank for a new one.
  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setWhy(initial?.why ?? "");
    const measure = initial?.measure ?? null;
    setMode(measure?.kind === "insight" ? "insight" : "hogql");
    setSql(measure?.kind === "hogql" ? measure.sql : "");
    setInsightUrl(measure?.kind === "insight" ? measure.url : "");
    setInsightName(measure?.kind === "insight" ? measure.name : "");
    setDirection(initial?.target?.direction ?? "at_least");
    setTargetValue(initial?.target ? String(initial.target.value) : "");
    setDueDate(initial?.target?.dueDate ?? "");
    resetSqlRun();
    resetInsightRun();
  }, [open, initial, resetSqlRun, resetInsightRun]);

  const parsedInsight = parsePostHogObjectUrl(insightUrl.trim());
  const insightShortId =
    parsedInsight?.kind === "insight"
      ? parsedInsight.id
      : /^[A-Za-z0-9_-]{6,20}$/.test(insightUrl.trim())
        ? insightUrl.trim()
        : null;

  const parsedTarget = targetValue.trim()
    ? Number(targetValue.replace(/,/g, ""))
    : null;
  const targetInvalid = parsedTarget !== null && !Number.isFinite(parsedTarget);
  const measureReady =
    mode === "agent" ||
    (mode === "hogql" && sql.trim().length > 0) ||
    (mode === "insight" && insightShortId !== null);
  const canSave =
    name.trim().length > 0 && !targetInvalid && measureReady && !isSaving;

  const buildMeasure = (): GoalMeasure | null => {
    if (mode === "hogql") return { kind: "hogql", sql: sql.trim() };
    if (mode === "insight" && insightShortId) {
      return {
        kind: "insight",
        shortId: insightShortId,
        url: insightUrl.trim().startsWith("http")
          ? insightUrl.trim()
          : `/insights/${insightShortId}`,
        name: insightName.trim() || insightRun.data?.name || insightShortId,
      };
    }
    return null;
  };

  const submit = async () => {
    if (!canSave) return;
    await onSubmit(
      {
        name: name.trim(),
        why: why.trim(),
        measure: buildMeasure(),
        target:
          parsedTarget !== null && Number.isFinite(parsedTarget)
            ? { direction, value: parsedTarget, dueDate: dueDate || null }
            : null,
      },
      { askAgent: mode === "agent" },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{initial ? "Edit goal" : "New goal"}</DialogTitle>
          <DialogDescription>
            One number, one target, and the reason it matters.
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
              <FieldLabel>Measure</FieldLabel>
              <ToggleGroup
                value={[mode]}
                onValueChange={(next: string[]) => {
                  const selected = next[0];
                  if (
                    selected === "hogql" ||
                    selected === "insight" ||
                    selected === "agent"
                  ) {
                    setMode(selected);
                  }
                }}
                aria-label="How the goal is measured"
                className="gap-1"
              >
                <ToggleGroupItem value="hogql" size="sm" variant="outline">
                  HogQL
                </ToggleGroupItem>
                <ToggleGroupItem value="insight" size="sm" variant="outline">
                  Insight
                </ToggleGroupItem>
                <ToggleGroupItem value="agent" size="sm" variant="outline">
                  Ask an agent
                </ToggleGroupItem>
              </ToggleGroup>
            </div>

            {mode === "hogql" ? (
              <>
                <div className="relative">
                  <Textarea
                    id="goal-sql"
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    placeholder={SQL_PLACEHOLDER}
                    disabled={isSaving}
                    spellCheck={false}
                    className="min-h-[120px] resize-y font-mono text-xs leading-relaxed"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    className="absolute top-2 right-2"
                    disabled={!sql.trim() || sqlRun.isPending}
                    onClick={() => sqlRun.mutate(sql)}
                  >
                    {sqlRun.isPending ? <Spinner /> : <PlayIcon size={12} />}
                    Run
                  </Button>
                </div>
                <FieldDescription>
                  The first cell of the first row is the current value.
                </FieldDescription>
                {sqlRun.isSuccess ? (
                  <ResultRow
                    label={
                      sqlRun.data.rows === 0
                        ? "The query returned no rows."
                        : sqlRun.data.value === null
                          ? `Returned ${sqlRun.data.rows} row(s), but the first row has no number.`
                          : `Current value from ${sqlRun.data.columns[0] ?? "the first column"}`
                    }
                    value={sqlRun.data.value}
                  />
                ) : null}
                {sqlRun.error ? (
                  <Text size="xs" className="text-destructive">
                    {sqlRun.error.message}
                  </Text>
                ) : null}
              </>
            ) : mode === "insight" ? (
              <>
                <div className="flex items-center gap-2">
                  <Input
                    id="goal-insight"
                    value={insightUrl}
                    onChange={(e) => setInsightUrl(e.target.value)}
                    placeholder="Paste an insight URL or its short id"
                    disabled={isSaving}
                    className="min-w-0 flex-1 font-mono text-xs"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    disabled={!insightShortId || insightRun.isPending}
                    onClick={() =>
                      insightShortId && insightRun.mutate(insightShortId)
                    }
                  >
                    {insightRun.isPending ? (
                      <Spinner />
                    ) : (
                      <PlayIcon size={12} />
                    )}
                    Check
                  </Button>
                </div>
                <Input
                  value={insightName}
                  onChange={(e) => setInsightName(e.target.value)}
                  placeholder={insightRun.data?.name ?? "Name (optional)"}
                  aria-label="Insight name"
                  disabled={isSaving}
                />
                <FieldDescription>
                  A trend reads as its total for the period. A funnel reads as
                  the conversion from first step to last, in percent.
                </FieldDescription>
                {insightRun.isSuccess ? (
                  <ResultRow
                    label={
                      insightRun.data.value === null
                        ? `${insightRun.data.name}: no single value could be read.`
                        : `Current value of ${insightRun.data.name}`
                    }
                    value={insightRun.data.value}
                  />
                ) : null}
                {insightRun.error ? (
                  <Text size="xs" className="text-destructive">
                    {insightRun.error.message}
                  </Text>
                ) : null}
              </>
            ) : (
              <div className="rounded-md bg-muted px-3 py-2.5">
                <Text size="xs">
                  An agent reads this space's context and the events in the
                  project, writes a HogQL measure for this goal, checks that it
                  returns one number, and adds it here.
                </Text>
                <Text size="xxs" variant="muted" className="mt-1">
                  The goal saves now without a measure. The task shows in the
                  feed. The number appears when it publishes.
                </Text>
              </div>
            )}
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
          {onDelete ? (
            <Button
              variant="destructive-outline"
              disabled={isSaving}
              onClick={() => void onDelete()}
              className="mr-auto"
            >
              Remove goal
            </Button>
          ) : null}
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
            {mode === "agent"
              ? "Save and ask agent"
              : initial
                ? "Save goal"
                : "Add goal"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResultRow({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-muted px-3 py-2">
      <Text size="xs" variant="muted">
        {label}
      </Text>
      {value !== null ? (
        <span className="font-semibold text-foreground text-lg tabular-nums">
          {formatNumber(value)}
        </span>
      ) : null}
    </div>
  );
}
