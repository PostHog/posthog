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
} from "@posthog/core/canvas/contextDocument";
import {
  looksLikeHogQL,
  parseGoalSentence,
} from "@posthog/core/canvas/goalComposer";
import { Button, cn, Input, Kbd, Text } from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMutation } from "@tanstack/react-query";
import {
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

interface GoalComposerProps {
  /** The goal being edited, or null for a new one. */
  initial: ContextGoal | null;
  onSave: (goal: ContextGoal) => Promise<void>;
  /** Hand the goal to a task when the instant draft cannot read the sentence. */
  onAskAgent: (goal: ContextGoal) => Promise<void>;
  onDelete?: () => Promise<void>;
  onClose: () => void;
  isSaving: boolean;
}

type Step = "ask" | "review";

function growToFit(el: HTMLTextAreaElement): void {
  el.style.height = "0px";
  el.style.height = `${Math.max(el.scrollHeight, 56)}px`;
}

/**
 * One line in, a goal out. A sentence saves the goal at once and hands the
 * measure to an agent that reads the project's events and writes the query.
 * Pasted HogQL skips the agent: the person sees the query and its current
 * value, adjusts the target, and saves.
 */
export function GoalComposer({
  initial,
  onSave,
  onAskAgent,
  onDelete,
  onClose,
  isSaving,
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

  // A fresh query is run once so the review shows a number next to it.
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

  const applyTarget = (target: GoalTarget | null) => {
    if (!target) return;
    setDirection(target.direction);
    setTargetValue(String(target.value));
    setDueDate(target.dueDate ?? "");
  };

  const parsedTarget = targetValue.trim()
    ? Number(targetValue.replace(/,/g, ""))
    : null;
  const targetInvalid = parsedTarget !== null && !Number.isFinite(parsedTarget);

  const buildGoal = (withMeasure: GoalMeasure | null): ContextGoal => ({
    name: name.trim() || "Untitled goal",
    why: initial?.why ?? "",
    measure: withMeasure,
    target:
      parsedTarget !== null && Number.isFinite(parsedTarget)
        ? { direction, value: parsedTarget, dueDate: dueDate || null }
        : null,
  });

  const save = async () => {
    if (targetInvalid || isSaving) return;
    await onSave(buildGoal(measure));
  };

  const askAgent = async () => {
    setAskedAgent(true);
    const parsed = parseGoalSentence(sentence.trim());
    if (!name.trim()) setName(parsed.name);
    applyTarget(parsed.target);
    await onAskAgent({
      ...buildGoal(null),
      name: name.trim() || parsed.name,
      target:
        parsed.target ??
        (parsedTarget !== null && Number.isFinite(parsedTarget)
          ? { direction, value: parsedTarget, dueDate: dueDate || null }
          : null),
    });
  };

  const proceed = async () => {
    const text = sentence.trim();
    if (!text || askedAgent) return;
    if (isHogQL) {
      setMeasure({ kind: "hogql", sql: text });
      if (!name.trim()) setName("Untitled goal");
      setStep("review");
      return;
    }
    await askAgent();
  };

  const onAskKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    const submit =
      (event.key === "Enter" && (event.metaKey || event.ctrlKey)) ||
      (event.key === "Enter" && !event.shiftKey && !isHogQL);
    if (submit) {
      event.preventDefault();
      void proceed();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {step === "ask" ? (
        <>
          <textarea
            ref={askRef}
            value={sentence}
            onChange={(e) => {
              setSentence(e.target.value);
              growToFit(e.target);
            }}
            onKeyDown={onAskKeyDown}
            disabled={askedAgent}
            spellCheck={!isHogQL}
            placeholder="Weekly completed checkouts above 1,200 by end of December"
            className={cn(
              "w-full resize-none bg-transparent text-foreground outline-none placeholder:text-muted-foreground/60",
              isHogQL
                ? "font-mono text-xs leading-relaxed"
                : "text-base leading-snug",
            )}
          />
          <div className="flex items-center justify-between gap-3">
            <Text size="xxs" variant="muted">
              {isHogQL
                ? "HogQL. The first cell of the first row is the value."
                : "Say what should move, how far, and by when. An agent finds the events and writes the query."}
            </Text>
            <div className="flex items-center gap-2">
              <Button variant="default" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!sentence.trim() || askedAgent}
                loading={askedAgent}
                onClick={() => void proceed()}
              >
                {isHogQL ? "Next" : "Add goal"}
                {!askedAgent ? <Kbd className="ml-1">↵</Kbd> : null}
              </Button>
            </div>
          </div>
        </>
      ) : (
        <>
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
              onChange={(e) => setName(e.target.value)}
              aria-label="Goal name"
              placeholder="Name this goal"
              className="w-full bg-transparent font-medium text-base text-foreground outline-none placeholder:text-muted-foreground/60"
            />
          </div>

          <MeasureReview
            measure={measure}
            onChange={(sql) => setMeasure({ kind: "hogql", sql })}
            onRun={(sql) => runMutate(sql)}
            value={run.data?.value ?? null}
            rows={run.data?.rows ?? null}
            running={run.isPending}
            error={run.error?.message ?? null}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Text size="xs" variant="muted" className="mr-1">
              Target
            </Text>
            <div className="flex overflow-hidden rounded-md border border-border">
              {(["at_least", "at_most"] as const).map((dir) => (
                <button
                  key={dir}
                  type="button"
                  onClick={() => setDirection(dir)}
                  className={cn(
                    "px-2 py-1 text-xs tabular-nums",
                    direction === dir
                      ? "bg-fill-selected text-foreground"
                      : "text-muted-foreground hover:bg-fill-hover",
                  )}
                >
                  {dir === "at_least" ? "≥" : "≤"}
                </button>
              ))}
            </div>
            <Input
              inputMode="decimal"
              value={targetValue}
              onChange={(e) => setTargetValue(e.target.value)}
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
              onChange={(e) => setDueDate(e.target.value)}
              aria-label="Due date"
              className="w-40"
            />
            {targetInvalid ? (
              <Text size="xxs" className="text-destructive">
                The target must be a number.
              </Text>
            ) : null}
          </div>

          <div className="flex items-center justify-between gap-3">
            <div>
              {onDelete ? (
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
            <div className="flex items-center gap-2">
              <Button variant="default" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={targetInvalid || isSaving || !name.trim()}
                loading={isSaving}
                onClick={() => void save()}
              >
                {initial ? "Save" : "Add goal"}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MeasureReview({
  measure,
  onChange,
  onRun,
  value,
  rows,
  running,
  error,
}: {
  measure: GoalMeasure | null;
  onChange: (sql: string) => void;
  onRun: (sql: string) => void;
  value: number | null;
  rows: number | null;
  running: boolean;
  error: string | null;
}) {
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
  const label = error
    ? error
    : running
      ? "Running"
      : rows === 0
        ? "No rows came back. Check the event name, for example $pageview."
        : value === null && rows !== null
          ? "No number in the first row. Return one row with one numeric cell."
          : rows !== null && rows > 1
            ? `First cell of the first row. The query returned ${rows} rows.`
            : "Current value";
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-background">
      <textarea
        value={sql}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => sql.trim() && onRun(sql)}
        spellCheck={false}
        rows={Math.min(8, Math.max(2, sql.split("\n").length))}
        aria-label="HogQL measure"
        className="w-full resize-none bg-transparent px-3 pt-2.5 font-mono text-foreground text-xs leading-relaxed outline-none"
      />
      <div className="flex items-center justify-between gap-3 border-border border-t px-3 py-1.5">
        <Text size="xxs" variant="muted">
          {label}
        </Text>
        <span className="font-semibold text-foreground text-sm tabular-nums">
          {running ? (
            <Spinner size="xs" aria-hidden="true" />
          ) : error ? (
            <WarningCircleIcon size={14} className="text-warning-foreground" />
          ) : value === null ? (
            "–"
          ) : (
            formatNumber(value)
          )}
        </span>
      </div>
    </div>
  );
}
