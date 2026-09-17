import {
  ArrowLeftIcon,
  ChartBarIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  type ContextGoal,
  firstNumericCell,
  formatNumber,
  type GoalDirection,
  type GoalMeasure,
  type GoalTarget,
  goalValueSuffix,
} from "@posthog/core/canvas/contextDocument";
import {
  looksLikeHogQL,
  parseGoalSentence,
} from "@posthog/core/canvas/goalComposer";
import {
  Button,
  cn,
  DialogBody,
  DialogFooter,
  Input,
  Kbd,
  Text,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import type { GoalMeasureTask } from "@posthog/ui/features/canvas/goalMeasureTasks";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation } from "@tanstack/react-query";
import {
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { SqlEditor, type SqlEditorHandle } from "./SqlEditor";

interface GoalComposerProps {
  initial: ContextGoal | null;
  onSave: (goal: ContextGoal) => Promise<void>;
  onAskAgent: (goal: ContextGoal) => Promise<void>;
  onDelete?: () => Promise<void>;
  onClose: () => void;
  isSaving: boolean;
  measureTask?: GoalMeasureTask | null;
  onOpenTask?: (taskId: string) => void;
  onRetryMeasure?: () => Promise<void>;
  takenNames: string[];
}

type Step = "ask" | "review";

const DIRECTIONS: readonly [GoalDirection, string][] = [
  ["at_least", "≥"],
  ["at_most", "≤"],
];

function growToFit(el: HTMLTextAreaElement): void {
  el.style.height = "0px";
  el.style.height = `${Math.max(el.scrollHeight, 56)}px`;
}

export function GoalComposer({
  initial,
  onSave,
  onAskAgent,
  onDelete,
  onClose,
  isSaving,
  takenNames,
  measureTask = null,
  onOpenTask,
  onRetryMeasure,
}: GoalComposerProps) {
  const client = useOptionalAuthenticatedClient();
  const [step, setStep] = useState<Step>(initial ? "review" : "ask");
  const [sentence, setSentence] = useState("");
  const [name, setName] = useState(initial?.name ?? "");
  const [measure, setMeasure] = useState<GoalMeasure | null>(
    initial?.measure ?? null,
  );
  const [direction, setDirection] = useState<GoalDirection>(
    initial?.target?.direction ?? "at_least",
  );
  const [targetValue, setTargetValue] = useState(
    initial?.target ? String(initial.target.value) : "",
  );
  const [dueDate, setDueDate] = useState(initial?.target?.dueDate ?? "");
  const [askedAgent, setAskedAgent] = useState(false);
  const askRef = useRef<HTMLTextAreaElement>(null);

  const isHogQL = looksLikeHogQL(sentence);
  const candidateName = name.trim().toLowerCase();
  const duplicate =
    candidateName.length > 0 &&
    takenNames.some((taken) => taken.trim().toLowerCase() === candidateName);
  const measureEmpty =
    measure === null || (measure.kind === "hogql" && !measure.sql.trim());
  const needsAgent = !initial && measureEmpty;

  const run = useMutation({
    mutationFn: async (sql: string) => {
      if (!client) throw new Error("Not signed in.");
      const grid = await client.runHogQLQuery(sql);
      return {
        value: firstNumericCell(grid.results),
        rows: grid.results.length,
      };
    },
  });
  const runMutate = run.mutate;

  useEffect(() => {
    if (step === "review" && measure?.kind === "hogql" && measure.sql.trim()) {
      runMutate(measure.sql);
    }
  }, [step, measure, runMutate]);

  useLayoutEffect(() => {
    const el = askRef.current;
    if (!el) return;
    growToFit(el);
    el.focus();
  }, []);

  const parsedTarget = targetValue.trim()
    ? Number(targetValue.replace(/,/g, ""))
    : null;
  const targetInvalid = parsedTarget !== null && !Number.isFinite(parsedTarget);
  const target: GoalTarget | null =
    parsedTarget !== null && !targetInvalid
      ? { direction, value: parsedTarget, dueDate: dueDate || null }
      : null;

  const proceed = () => {
    const text = sentence.trim();
    if (!text) return;
    if (isHogQL) {
      setMeasure({ kind: "hogql", sql: text });
    } else {
      const parsed = parseGoalSentence(text);
      setName(sentenceCase(parsed.name));
      if (parsed.target) {
        setDirection(parsed.target.direction);
        setTargetValue(String(parsed.target.value));
        setDueDate(parsed.target.dueDate ?? "");
      }
    }
    setStep("review");
  };

  const canSubmit =
    !targetInvalid &&
    !isSaving &&
    !askedAgent &&
    !duplicate &&
    name.trim() !== "";

  const submit = async () => {
    if (!canSubmit) return;
    const goal: ContextGoal = {
      name: sentenceCase(name.trim()) || "Untitled goal",
      why: initial?.why ?? "",
      measure: measureEmpty ? null : measure,
      primary: initial?.primary ?? false,
      target,
    };
    if (needsAgent) {
      setAskedAgent(true);
      await onAskAgent(goal);
    } else {
      await onSave(goal);
    }
  };

  const onAskKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    const next =
      (event.key === "Enter" && (event.metaKey || event.ctrlKey)) ||
      (event.key === "Enter" && !event.shiftKey && !isHogQL);
    if (next) {
      event.preventDefault();
      proceed();
    }
  };

  const note = reviewNote({ duplicate, targetInvalid, needsAgent });

  return (
    <>
      <DialogBody>
        {step === "ask" ? (
          <div className="flex flex-col gap-3">
            <textarea
              ref={askRef}
              value={sentence}
              onChange={(event) => {
                setSentence(event.target.value);
                growToFit(event.target);
              }}
              onKeyDown={onAskKeyDown}
              spellCheck={!isHogQL}
              placeholder="Weekly completed checkouts above 1,200 by end of December"
              className={cn(
                "w-full resize-none bg-transparent text-foreground outline-none placeholder:text-muted-foreground/60",
                isHogQL
                  ? "font-mono text-xs leading-relaxed"
                  : "text-base leading-snug",
              )}
            />
            <Text size="xs" variant="muted">
              {isHogQL
                ? "HogQL. The first cell of the first row is the value."
                : "The name, the target and the date are read from the sentence. You check them next."}
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-start gap-2">
              {!initial ? (
                <Button
                  variant="default"
                  size="icon-xs"
                  aria-label="Back to the sentence"
                  onClick={() => setStep("ask")}
                >
                  <ArrowLeftIcon size={13} />
                </Button>
              ) : null}
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label="Goal name"
                placeholder="Name this goal"
                aria-invalid={duplicate || undefined}
                className="-mx-1 w-full rounded-md bg-transparent px-1 font-medium text-base text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 hover:bg-fill-hover focus:bg-fill-hover"
              />
            </div>

            {initial && measure === null && measureTask ? (
              <MeasureTaskPanel
                task={measureTask}
                disabled={isSaving}
                onOpenTask={(taskId) => {
                  onOpenTask?.(taskId);
                  onClose();
                }}
                onRetry={onRetryMeasure}
              />
            ) : (
              <MeasureReview
                measure={measure}
                onChange={(sql) =>
                  setMeasure((prev) =>
                    prev?.kind === "hogql"
                      ? { ...prev, sql }
                      : { kind: "hogql", sql },
                  )
                }
                onRun={runMutate}
                result={{
                  running: run.isPending,
                  error: run.error?.message ?? null,
                  rows: run.data?.rows ?? null,
                  value: run.data?.value ?? null,
                }}
                unit={goalValueSuffix(name)}
              />
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Text size="xs" variant="muted" className="mr-1">
                Target
              </Text>
              <div className="flex overflow-hidden rounded-md border border-border">
                {DIRECTIONS.map(([option, sign]) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setDirection(option)}
                    className={cn(
                      "px-2 py-1 text-xs tabular-nums",
                      direction === option
                        ? "bg-fill-selected text-foreground"
                        : "text-muted-foreground hover:bg-fill-hover",
                    )}
                  >
                    {sign}
                  </button>
                ))}
              </div>
              <Input
                inputMode="decimal"
                value={targetValue}
                onChange={(event) => setTargetValue(event.target.value)}
                placeholder="1,200"
                aria-label="Target value"
                aria-invalid={targetInvalid || undefined}
                className="w-28 tabular-nums"
              />
              <Text size="xs" variant="muted">
                by
              </Text>
              <Input
                type="date"
                value={dueDate}
                onChange={(event) => setDueDate(event.target.value)}
                aria-label="Due date"
                className="w-40"
              />
            </div>
            {note ? (
              <Text
                size="xs"
                variant={note.tone === "muted" ? "muted" : undefined}
                className={
                  note.tone === "warning"
                    ? "text-warning-foreground"
                    : undefined
                }
              >
                {note.text}
              </Text>
            ) : null}
          </div>
        )}
      </DialogBody>
      <DialogFooter className="items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          {step === "review" && onDelete ? (
            <Button
              variant="destructive-outline"
              size="sm"
              disabled={isSaving}
              onClick={() => void onDelete()}
            >
              Remove goal
            </Button>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          {step === "ask" ? (
            <Button
              variant="primary"
              size="sm"
              disabled={!sentence.trim()}
              onClick={proceed}
            >
              Next
              <Kbd className="ml-1">↵</Kbd>
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              disabled={!canSubmit}
              loading={isSaving || askedAgent}
              onClick={() => void submit()}
            >
              {initial ? "Save" : "Add goal"}
            </Button>
          )}
        </div>
      </DialogFooter>
    </>
  );
}

function MeasureTaskPanel({
  task,
  disabled,
  onOpenTask,
  onRetry,
}: {
  task: GoalMeasureTask;
  disabled: boolean;
  onOpenTask: (taskId: string) => void;
  onRetry?: () => Promise<void>;
}) {
  const running = task.state === "running";
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        {running ? (
          <Spinner size="xs" aria-hidden="true" />
        ) : (
          <WarningCircleIcon
            size={14}
            className="shrink-0 text-warning-foreground"
          />
        )}
        <Text size="xs">
          {running
            ? "An agent is writing the measure. It reads the project's events, writes the query, and updates this goal."
            : "The agent finished without a measure."}
        </Text>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          variant="outline"
          size="xs"
          onClick={() => onOpenTask(task.taskId)}
        >
          Open task
        </Button>
        {!running && onRetry ? (
          <Button
            variant="outline"
            size="xs"
            disabled={disabled}
            onClick={() => void onRetry()}
          >
            Try again
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function sentenceCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface ReviewNote {
  text: string;
  tone: "warning" | "muted";
}

function reviewNote(state: {
  duplicate: boolean;
  targetInvalid: boolean;
  needsAgent: boolean;
}): ReviewNote | null {
  if (state.duplicate) {
    return { text: "A goal with this name already exists.", tone: "warning" };
  }
  if (state.targetInvalid) {
    return { text: "The target must be a number.", tone: "warning" };
  }
  if (state.needsAgent) {
    return {
      text: "No query yet. An agent finds the events and writes one after you add the goal.",
      tone: "muted",
    };
  }
  return null;
}

interface RunResult {
  running: boolean;
  error: string | null;
  rows: number | null;
  value: number | null;
}

function resultLabel(sql: string, result: RunResult): string {
  if (result.error) return result.error;
  if (result.running) return "Running";
  if (!sql.trim()) return "No query yet";
  if (result.rows === 0) {
    return "No rows came back. Check the event name, for example $pageview.";
  }
  if (result.rows !== null && result.value === null) {
    return "No number in the first row. Return one row with one numeric cell.";
  }
  if (result.rows !== null && result.rows > 1) {
    return `First cell of the first row. The query returned ${result.rows} rows.`;
  }
  return "Current value";
}

function ResultValue({ result, unit }: { result: RunResult; unit: string }) {
  if (result.running) return <Spinner size="xs" aria-hidden="true" />;
  if (result.error) {
    return <WarningCircleIcon size={14} className="text-warning-foreground" />;
  }
  if (result.value === null) return "–";
  return (
    <>
      {formatNumber(result.value)}
      {unit}
    </>
  );
}

function MeasureReview({
  measure,
  onChange,
  onRun,
  result,
  unit,
}: {
  measure: GoalMeasure | null;
  onChange: (sql: string) => void;
  onRun: (sql: string) => void;
  result: RunResult;
  unit: string;
}) {
  const editorRef = useRef<SqlEditorHandle>(null);

  if (measure?.kind === "insight") {
    return (
      <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2">
        <ChartBarIcon size={14} className="text-muted-foreground" />
        <Text size="xs">
          Measured by the insight <strong>{measure.name}</strong>.
        </Text>
      </div>
    );
  }
  const sql = measure?.kind === "hogql" ? measure.sql : "";
  return (
    <div className="flex flex-col overflow-hidden rounded-md border border-border bg-background">
      <SqlEditor
        ref={editorRef}
        initialValue={sql}
        onChange={onChange}
        onRun={(next) => {
          if (next.trim()) onRun(next);
        }}
      />
      <div className="flex items-center justify-between gap-3 border-border border-t px-3 py-1.5">
        <Button
          variant="link-muted"
          size="xs"
          disabled={result.running || !sql.trim()}
          onClick={() => {
            editorRef.current?.format();
            onRun(sql);
          }}
        >
          Run
          <Kbd className="ml-1">⌘↵</Kbd>
        </Button>
        <span className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <Text
            size="xs"
            variant="muted"
            className={cn(
              "min-w-0 truncate",
              result.error && "text-warning-foreground",
            )}
          >
            {resultLabel(sql, result)}
          </Text>
          <span className="shrink-0 font-semibold text-foreground text-sm tabular-nums">
            <ResultValue result={result} unit={unit} />
          </span>
        </span>
      </div>
    </div>
  );
}
