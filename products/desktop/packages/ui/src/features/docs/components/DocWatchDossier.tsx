import { CheckIcon, XIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { useMemo, useRef, useState } from "react";
import { Spark } from "../extensions/DataValue";
import {
  type TimelineEntry,
  type TimelineKind,
  watchTimeline,
} from "../hooks/watchTimeline";
import { personName } from "./DocPostRow";
import {
  DecideDialog,
  type Decision,
  VerdictPill,
  WatchHeaderActions,
} from "./DocWatchCard";

type Watch = DocSchemas.DocWatch;

const CHART = { width: 240, height: 44 };

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

function timeLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** The hero: where the claim stands, in one sentence, and one line of when. */
function standing(
  watch: Watch,
  since: string,
  decider: string,
): { line: string; meta: string } {
  const verdict = watch.verdict;
  const decidedAt = dayLabel(verdict.at);
  if (watch.status === "stopped" && watch.stopped_reason === "verdict") {
    return {
      line: verdict.reason || "The claim was decided.",
      meta: `Decided by ${decider}${decidedAt ? ` · ${decidedAt}` : ""}`,
    };
  }
  if (watch.status === "stopped") {
    const why = watch.stopped_reason ? STOP_LABEL[watch.stopped_reason] : "";
    return {
      line: why ? `Stopped, ${why}.` : "Stopped.",
      meta: `Watched since ${dayLabel(since)}`,
    };
  }
  if (watch.status === "paused") {
    return {
      line: "Paused while the page is done.",
      meta: "Reopen the page to watch again",
    };
  }
  if (!watch.brief) {
    return {
      line: "The agent is turning the claim into checks.",
      meta: "A brief lands here in a minute",
    };
  }
  const numbers = watch.brief.evidence.length;
  const next = watch.next_check_at
    ? `Next check ${timeLabel(watch.next_check_at)}`
    : "";
  const scout = watch.evidence_only
    ? ""
    : watch.scout
      ? "The scout looks daily"
      : watch.scout_error
        ? "No scout"
        : "The scout is starting";
  const meta = [next, scout].filter(Boolean).join(" · ");
  if (verdict.verdict === "moved") {
    return {
      line: `${verdict.reason || "A number left its baseline."}${watch.scout ? " The scout is looking into why." : ""}`,
      meta,
    };
  }
  if (verdict.verdict === "stale") {
    return {
      line: verdict.reason
        ? `Could not check: ${verdict.reason}`
        : "The last check could not run.",
      meta,
    };
  }
  return {
    line:
      numbers > 0
        ? `${numbers === 1 ? "The number holds" : `All ${plural(numbers, "number")} hold`} since ${dayLabel(since)}.`
        : `No numbers to recheck. The claim holds since ${dayLabel(since)}.`,
    meta,
  };
}

/** One of the two outcomes: what settles the claim that way, and who chose it. */
function Door({
  side,
  text,
  watch,
  onDecide,
}: {
  side: Decision;
  text: string;
  watch: Watch;
  onDecide: (side: Decision) => void;
}) {
  const decided =
    watch.status === "stopped" &&
    (watch.verdict.verdict === "confirmed" ||
      watch.verdict.verdict === "refuted");
  const lit = decided ? watch.verdict.verdict === side : null;
  const clickable = watch.status === "active" && !!watch.brief;
  const body = (
    <>
      <span className="doc-door-head">
        <span className="doc-door-icon">
          {side === "confirmed" ? (
            <CheckIcon size={12} weight="bold" />
          ) : (
            <XIcon size={12} weight="bold" />
          )}
        </span>
        <span className="doc-door-label">
          {side === "confirmed" ? "Confirmed" : "Refuted"}
          <span className="doc-door-if"> if</span>
        </span>
        {clickable ? <span className="doc-door-cta">Decide →</span> : null}
      </span>
      <span className="doc-door-text">{text || "Not written yet."}</span>
      {lit ? (
        <span className="doc-door-foot">
          Decided{watch.verdict.at ? ` · ${dayLabel(watch.verdict.at)}` : ""}
        </span>
      ) : null}
    </>
  );
  if (clickable) {
    return (
      <button
        type="button"
        className="doc-door"
        data-side={side}
        onClick={() => onDecide(side)}
      >
        {body}
      </button>
    );
  }
  return (
    <div className="doc-door" data-side={side} data-lit={lit ?? undefined}>
      {body}
    </div>
  );
}

/** One number as a tile: the figure, its change, and the line of its checks. */
function NumberTile({ evidence }: { evidence: DocSchemas.WatchEvidence }) {
  const [showSql, setShowSql] = useState(false);
  const points = evidence.history
    .map((entry) => entry[1])
    .filter((value): value is number => typeof value === "number");
  const delta =
    evidence.baseline !== null && evidence.value !== null
      ? evidence.value - evidence.baseline
      : null;
  const share =
    delta !== null && evidence.baseline
      ? Math.round((Math.abs(delta) / Math.abs(evidence.baseline)) * 100)
      : null;
  const change = evidence.error
    ? "could not check"
    : delta === null
      ? ""
      : delta === 0
        ? "unchanged"
        : `${delta > 0 ? "+" : "−"}${share ? `${share}%` : formatNumber(Math.abs(delta))}`;
  return (
    <div className="doc-tile" data-moved={evidence.moved}>
      <div className="doc-tile-head">
        <span className="doc-tile-label">{evidence.label || "evidence"}</span>
        <button
          type="button"
          className="doc-tile-sql"
          onClick={() => setShowSql((open) => !open)}
        >
          SQL
        </button>
      </div>
      <div className="doc-tile-row">
        <span className="doc-tile-figure">{formatNumber(evidence.value)}</span>
        {change ? <span className="doc-tile-change">{change}</span> : null}
      </div>
      {points.length > 1 ? (
        <Spark points={points} size={CHART} className="doc-tile-chart" />
      ) : null}
      <div className="doc-tile-foot">
        <span>from {formatNumber(evidence.baseline)}</span>
        <span>{plural(Math.max(points.length, 1), "check")}</span>
      </div>
      {showSql ? (
        <div className="doc-tile-code">
          <HighlightedCode code={evidence.query} language="sql" />
        </div>
      ) : null}
    </div>
  );
}

const KIND_LABEL: Record<TimelineKind, string> = {
  started: "Started",
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
  comment: "Comment",
};

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  const [open, setOpen] = useState(false);
  const expandable =
    (!!entry.body && entry.body.trim() !== entry.title.trim()) ||
    entry.title.length > 90;
  const kind =
    entry.kind === "started" || entry.kind === "comment"
      ? ""
      : KIND_LABEL[entry.kind];
  const meta = [kind, entry.who, timeLabel(entry.at)]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="doc-timeline-row" data-kind={entry.kind}>
      <span className="doc-timeline-dot" />
      <div className="min-w-0">
        <div className="doc-timeline-text" data-open={open}>
          {open && entry.body ? (
            <span className="whitespace-pre-wrap break-words">
              {entry.body.replace(/\*\*/g, "")}
            </span>
          ) : (
            entry.title
          )}
        </div>
        <div className="doc-timeline-meta">
          {meta}
          {expandable ? (
            <button
              type="button"
              className="doc-timeline-more"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "less" : "more"}
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

/**
 * The whole of a watch with room to read: where it stands, the two ways it
 * settles, the numbers as tiles, what the scout follows, and everything that
 * happened in a rail on the right. The thread stays a conversation; this is
 * the record.
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
  const decidedAt = Date.parse(watch.verdict.at ?? "");
  const decider =
    entries
      .filter((entry) => entry.kind === "verdict" && entry.who)
      .sort(
        (left, right) =>
          Math.abs(Date.parse(left.at) - decidedAt) -
          Math.abs(Date.parse(right.at) - decidedAt),
      )[0]?.who || (watch.verdict.by ? BY_LABEL[watch.verdict.by] : "");
  const hero = standing(watch, thread.created_at, decider);
  const busy = pendingAction !== null && pendingAction !== "arm";
  const focusPopup = (): boolean | HTMLElement | null => popupRef.current;
  const nextCheck =
    watch.status === "active" && brief && watch.next_check_at
      ? watch.next_check_at
      : null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          ref={popupRef}
          size="wide"
          className="doc-dossier"
          initialFocus={focusPopup}
        >
          <DialogHeader>
            <div className="flex items-start gap-3 pr-8">
              <DialogTitle className="doc-dossier-title min-w-0 flex-1">
                “{thread.anchor_text || "a section"}”
              </DialogTitle>
              <div className="flex shrink-0 items-center gap-1">
                <WatchHeaderActions
                  watch={watch}
                  onAction={onAction}
                  pendingAction={pendingAction}
                />
              </div>
            </div>
          </DialogHeader>

          <DialogBody className="doc-dossier-scroll">
            <div className="doc-dossier-body">
              <div className="doc-dossier-main">
                <div className="doc-hero">
                  <VerdictPill watch={watch} className="doc-verdict-lg" />
                  <div className="min-w-0">
                    <div className="doc-hero-line">{hero.line}</div>
                    {hero.meta ? (
                      <div className="doc-hero-meta">{hero.meta}</div>
                    ) : null}
                  </div>
                </div>

                {brief && (brief.confirms || brief.refutes) ? (
                  <section>
                    <h4 className="doc-dossier-heading">How it settles</h4>
                    <div className="doc-doors">
                      <Door
                        side="confirmed"
                        text={brief.confirms}
                        watch={watch}
                        onDecide={setDeciding}
                      />
                      <Door
                        side="refuted"
                        text={brief.refutes}
                        watch={watch}
                        onDecide={setDeciding}
                      />
                    </div>
                  </section>
                ) : null}

                {brief && brief.evidence.length > 0 ? (
                  <section>
                    <h4 className="doc-dossier-heading">Numbers</h4>
                    <div className="doc-tiles">
                      {brief.evidence.map((evidence) => (
                        <NumberTile
                          key={`${evidence.label}:${evidence.query}`}
                          evidence={evidence}
                        />
                      ))}
                    </div>
                  </section>
                ) : null}

                {brief && brief.signals.length > 0 ? (
                  <section>
                    <h4 className="doc-dossier-heading">
                      Scout follows
                      {watch.scout_error ? (
                        <span className="doc-dossier-heading-note">
                          {watch.scout_error}
                        </span>
                      ) : null}
                    </h4>
                    <ul className="doc-watch-signals">
                      {brief.signals.map((signal) => (
                        <li key={signal} className="doc-watch-signal">
                          {signal}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </div>

              <aside className="doc-dossier-rail">
                <h4 className="doc-dossier-heading">History</h4>
                <ul
                  className="doc-timeline"
                  data-verdict={watch.verdict.verdict}
                >
                  {nextCheck ? (
                    <li className="doc-timeline-row" data-kind="next">
                      <span className="doc-timeline-dot" />
                      <div className="min-w-0">
                        <div className="doc-timeline-text">Next check</div>
                        <div className="doc-timeline-meta">
                          {timeLabel(nextCheck)}
                        </div>
                      </div>
                    </li>
                  ) : null}
                  {entries.map((entry) => (
                    <TimelineRow key={entry.id} entry={entry} />
                  ))}
                </ul>
              </aside>
            </div>
          </DialogBody>
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
