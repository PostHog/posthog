import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { useMemo, useRef, useState } from "react";
import { Spark } from "../extensions/DataValue";
import {
  type TimelineEntry,
  type TimelineKind,
  watchTimeline,
} from "../hooks/watchTimeline";
import { personName } from "./DocPostRow";
import { DecideDialog, type Decision } from "./DocWatchCard";

type Watch = DocSchemas.DocWatch;

const SPARK = { width: 48, height: 14 };

const STOP_LABEL: Record<DocSchemas.WatchStopReason, string> = {
  section_removed: "the words left the page",
  page_done: "the page is done",
  page_deleted: "the page was deleted",
  handled: "it was marked handled",
  person: "someone stopped it",
  verdict: "it was decided",
};

const BY_LABEL: Record<DocSchemas.WatchActor, string> = {
  agent: "the agent",
  person: "a person",
  page: "the numbers",
};

const KIND_LABEL: Record<TimelineKind, string> = {
  started: "Watch started",
  brief: "Brief",
  check: "Check",
  moved: "Moved",
  stale: "Could not check",
  report: "Scout report",
  verdict: "Decision",
  scout: "Scout",
  stopped: "Stopped",
  paused: "Paused",
  resumed: "Resumed",
  comment: "",
};

function formatNumber(value: number | null): string {
  if (value === null) return "—";
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function dayLabel(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function clockLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      });
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** A signal reads as words: object tags keep their name, the trailing period goes. */
function plainSignal(signal: string): string {
  return signal.replace(/<(\w+)[^>]*>(.*?)<\/\1>/g, "$2").replace(/\.$/, "");
}

function lowerFirst(text: string): string {
  return text ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

function change(evidence: DocSchemas.WatchEvidence): string {
  if (evidence.error) return "could not check";
  if (evidence.baseline === null || evidence.value === null) return "";
  const delta = evidence.value - evidence.baseline;
  if (delta === 0) return "unchanged";
  const share = evidence.baseline
    ? Math.round((Math.abs(delta) / Math.abs(evidence.baseline)) * 100)
    : 0;
  const sign = delta > 0 ? "+" : "−";
  return share > 0
    ? `${sign}${share}%`
    : `${sign}${formatNumber(Math.abs(delta))}`;
}

/** The state line: the state word, then the facts behind it, in one line. */
function stateLine(
  watch: Watch,
  since: string,
  decider: string,
): { word: string; rest: string[] } {
  const verdict = watch.verdict;
  if (watch.status === "stopped" && watch.stopped_reason === "verdict") {
    return {
      word: verdict.verdict === "confirmed" ? "Confirmed" : "Refuted",
      rest: [
        decider ? `by ${decider}` : "",
        dayLabel(verdict.at),
        lowerFirst(verdict.reason),
      ].filter(Boolean),
    };
  }
  if (watch.status === "stopped") {
    const why = watch.stopped_reason ? STOP_LABEL[watch.stopped_reason] : "";
    return { word: "Stopped", rest: [why].filter(Boolean) };
  }
  if (watch.status === "paused") {
    return { word: "Paused", rest: ["the page is done"] };
  }
  if (!watch.brief) {
    return {
      word: "Compiling",
      rest: ["the agent is turning the claim into checks"],
    };
  }
  const next = watch.next_check_at
    ? `next check ${dayLabel(watch.next_check_at)} ${clockLabel(watch.next_check_at)}`
    : "";
  if (verdict.verdict === "moved") {
    return {
      word: "Moved",
      rest: [
        lowerFirst(verdict.reason),
        watch.scout ? "the scout is looking into why" : "",
      ].filter(Boolean),
    };
  }
  if (verdict.verdict === "stale") {
    return {
      word: "Could not check",
      rest: [lowerFirst(verdict.reason), next].filter(Boolean),
    };
  }
  const numbers = watch.brief.evidence.length;
  return {
    word: "Holding",
    rest: [
      numbers > 0
        ? `${numbers === 1 ? "the number holds" : `all ${plural(numbers, "number")} hold`} since ${dayLabel(since)}`
        : `nothing has moved since ${dayLabel(since)}`,
      next,
    ].filter(Boolean),
  };
}

/** One row of the ledger: what kind of thing on the left, the thing on the right. */
function Row({
  label,
  children,
  tone,
  ...rest
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  tone?: "confirmed" | "refuted";
} & Omit<React.HTMLAttributes<HTMLDivElement>, "children">) {
  return (
    <div className="doc-ledger-row" data-tone={tone} {...rest}>
      <div className="doc-ledger-label">{label}</div>
      <div className="doc-ledger-content">{children}</div>
    </div>
  );
}

function NumberLine({ evidence }: { evidence: DocSchemas.WatchEvidence }) {
  const points = evidence.history
    .map((entry) => entry[1])
    .filter((value): value is number => typeof value === "number");
  return (
    <div className="doc-ledger-number" data-moved={evidence.moved}>
      <span className="doc-ledger-number-name">
        {evidence.label || "evidence"}
      </span>
      {points.length > 2 ? (
        <Spark points={points} size={SPARK} className="doc-ledger-spark" />
      ) : null}
      <span className="doc-ledger-figure">{formatNumber(evidence.value)}</span>
      <span className="doc-ledger-change">{change(evidence)}</span>
    </div>
  );
}

function HistoryRow({ entry }: { entry: TimelineEntry }) {
  const [open, setOpen] = useState(false);
  const body = entry.body?.replace(/\*\*/g, "");
  const expandable =
    (!!body && body.trim() !== entry.title.trim()) || entry.title.length > 110;
  const head = KIND_LABEL[entry.kind];
  const text =
    entry.kind === "started" ? head : open && body ? body : entry.title;
  return (
    <Row
      label={
        <>
          {dayLabel(entry.at)}{" "}
          <span className="doc-ledger-clock">{clockLabel(entry.at)}</span>
        </>
      }
      data-kind={entry.kind}
    >
      <div className="doc-ledger-text" data-open={open}>
        {text}
      </div>
      <div className="doc-ledger-muted">
        {[entry.kind === "started" ? "" : head, entry.who]
          .filter(Boolean)
          .join(" · ")}
        {expandable ? (
          <button
            type="button"
            className="doc-ledger-more"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "less" : "more"}
          </button>
        ) : null}
      </div>
    </Row>
  );
}

/**
 * The record of a watch as one ledger: a label column on the left, the
 * content on the right, for the terms and for the history alike. The state
 * sits under the claim; the decisions sit in the footer.
 */
export function DocWatchDossier({
  thread,
  open,
  onOpenChange,
  onAction,
  pendingAction,
}: {
  thread: DocSchemas.DiscussionThread;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAction: (body: DocSchemas.WatchActionBody) => void;
  pendingAction: DocSchemas.WatchActionKind | null;
}) {
  const [deciding, setDeciding] = useState<Decision | null>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const watch = thread.watch;
  const entries = useMemo(
    () => watchTimeline(thread, personName).reverse(),
    [thread],
  );
  if (!watch) return null;
  const brief = watch.brief;
  const active = watch.status === "active";
  const decided =
    watch.status === "stopped" &&
    (watch.verdict.verdict === "confirmed" ||
      watch.verdict.verdict === "refuted");
  const decidedAt = Date.parse(watch.verdict.at ?? "");
  const decider =
    entries
      .filter((entry) => entry.kind === "verdict" && entry.who)
      .sort(
        (left, right) =>
          Math.abs(Date.parse(left.at) - decidedAt) -
          Math.abs(Date.parse(right.at) - decidedAt),
      )[0]?.who ||
    (watch.verdict.by && watch.verdict.by !== "person"
      ? BY_LABEL[watch.verdict.by]
      : "");
  const state = stateLine(watch, thread.created_at, decider);
  const busy = pendingAction !== null && pendingAction !== "arm";
  const nextCheck = active && brief ? watch.next_check_at : null;
  const focusPopup = (): boolean | HTMLElement | null => popupRef.current;
  const tone = (side: Decision) =>
    decided ? (watch.verdict.verdict === side ? "lit" : "dim") : undefined;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          ref={popupRef}
          className="doc-dossier"
          initialFocus={focusPopup}
        >
          <DialogHeader>
            <div className="doc-ledger-eyebrow">Watch</div>
            <DialogTitle className="doc-dossier-title">
              “{thread.anchor_text || "a section"}”
            </DialogTitle>
            <div
              className="doc-ledger-state"
              data-verdict={watch.verdict.verdict}
              data-status={watch.status}
            >
              <span className="doc-ledger-dot" />
              <span className="doc-ledger-state-word">{state.word}</span>
              {state.rest.map((part) => (
                <span key={part} className="doc-ledger-state-part">
                  {part}
                </span>
              ))}
            </div>
          </DialogHeader>

          <DialogBody className="doc-dossier-scroll">
            {brief &&
            (brief.confirms ||
              brief.refutes ||
              brief.evidence.length > 0 ||
              brief.signals.length > 0) ? (
              <div className="doc-ledger">
                {brief.confirms ? (
                  <Row
                    tone="confirmed"
                    data-decided={tone("confirmed")}
                    label={
                      <>
                        <b>Confirmed</b> if
                      </>
                    }
                  >
                    {brief.confirms}
                  </Row>
                ) : null}
                {brief.refutes ? (
                  <Row
                    tone="refuted"
                    data-decided={tone("refuted")}
                    label={
                      <>
                        <b>Refuted</b> if
                      </>
                    }
                  >
                    {brief.refutes}
                  </Row>
                ) : null}
                {brief.evidence.length > 0 ? (
                  <Row label="Numbers">
                    <div className="flex flex-col gap-1.5">
                      {brief.evidence.map((evidence) => (
                        <NumberLine
                          key={`${evidence.label}:${evidence.query}`}
                          evidence={evidence}
                        />
                      ))}
                    </div>
                  </Row>
                ) : null}
                {brief.signals.length > 0 ? (
                  <Row label="Signals">
                    <div className="doc-ledger-chips">
                      {brief.signals.map((signal) => (
                        <span key={signal} className="doc-ledger-chip">
                          {plainSignal(signal)}
                        </span>
                      ))}
                    </div>
                    {watch.scout_error ? (
                      <div className="doc-ledger-muted doc-ledger-warn">
                        {watch.scout_error}
                      </div>
                    ) : null}
                  </Row>
                ) : null}
              </div>
            ) : null}

            <div className="doc-ledger">
              {nextCheck ? (
                <Row
                  data-kind="next"
                  label={
                    <>
                      {dayLabel(nextCheck)}{" "}
                      <span className="doc-ledger-clock">
                        {clockLabel(nextCheck)}
                      </span>
                    </>
                  }
                >
                  <div className="doc-ledger-text">Next check</div>
                </Row>
              ) : null}
              {entries.map((entry) => (
                <HistoryRow key={entry.id} entry={entry} />
              ))}
            </div>
          </DialogBody>

          {decided ? null : (
            <DialogFooter className="doc-ledger-footer">
              <div className="flex flex-1 items-center gap-1">
                {active && brief && brief.evidence.length > 0 ? (
                  <Button
                    variant="link-muted"
                    disabled={busy}
                    onClick={() => onAction({ action: "check" })}
                  >
                    {pendingAction === "check" ? "Checking…" : "Check now"}
                  </Button>
                ) : null}
              </div>
              {decided ? null : active ? (
                <>
                  <Button
                    variant="link-muted"
                    disabled={busy}
                    onClick={() => onAction({ action: "stop" })}
                  >
                    Stop watching
                  </Button>
                  {brief ? (
                    <>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => setDeciding("refuted")}
                      >
                        Refute
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => setDeciding("confirmed")}
                      >
                        Confirm
                      </Button>
                    </>
                  ) : null}
                </>
              ) : (
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => onAction({ action: "resume" })}
                >
                  Watch again
                </Button>
              )}
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
      <DecideDialog
        decision={deciding}
        onClose={() => setDeciding(null)}
        isPending={busy}
        onDecide={(decision, reason) => {
          onAction({ action: "close", verdict: decision, reason });
          setDeciding(null);
        }}
      />
    </>
  );
}
