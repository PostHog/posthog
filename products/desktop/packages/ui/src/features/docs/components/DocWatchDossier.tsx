import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { useMemo, useState } from "react";
import { Spark } from "../extensions/DataValue";
import {
  type TimelineEntry,
  type TimelineKind,
  watchTimeline,
} from "../hooks/watchTimeline";
import { personName } from "./DocPostRow";
import { VerdictPill, WatchHeaderActions } from "./DocWatchCard";

const CHART = { width: 320, height: 72 };

function formatNumber(value: number | null): string {
  if (value === null) return "—";
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function dayLabel(iso: string): string {
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

/** One number over time: the figure, its change, and the line of every check. */
function EvidenceChart({ evidence }: { evidence: DocSchemas.WatchEvidence }) {
  const [showSql, setShowSql] = useState(false);
  const points = evidence.history
    .map((entry) => entry[1])
    .filter((value): value is number => typeof value === "number");
  const first = evidence.history[0]?.[0];
  const last = evidence.history[evidence.history.length - 1]?.[0];
  const delta =
    evidence.baseline !== null && evidence.value !== null
      ? evidence.value - evidence.baseline
      : null;
  const share =
    delta !== null && evidence.baseline
      ? Math.round((Math.abs(delta) / Math.abs(evidence.baseline)) * 100)
      : null;
  return (
    <div className="doc-dossier-evidence" data-moved={evidence.moved}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate text-(--gray-12) text-[13px]">
          {evidence.label || "evidence"}
        </span>
        <span className="doc-dossier-figure">
          {formatNumber(evidence.value)}
        </span>
      </div>
      <div className="mt-0.5 flex items-baseline justify-between gap-3 text-[11.5px]">
        <span className="text-(--gray-10)">
          baseline {formatNumber(evidence.baseline)}
          {evidence.checked_at
            ? ` · checked ${formatRelativeTimeShort(evidence.checked_at)} ago`
            : ""}
        </span>
        <span className="doc-dossier-delta">
          {evidence.error
            ? evidence.error
            : delta === null
              ? ""
              : delta === 0
                ? "unchanged"
                : `${delta > 0 ? "+" : "−"}${share ? `${share}%` : formatNumber(Math.abs(delta))}`}
        </span>
      </div>
      {points.length > 1 ? (
        <div className="mt-2">
          <div className="border-(--gray-5) border-b pb-px">
            <Spark points={points} size={CHART} className="doc-card-chart" />
          </div>
          <div className="mt-1 flex justify-between text-(--gray-10) text-[10px]">
            <span>{first ? dayLabel(first) : ""}</span>
            <span>
              {points.length} {points.length === 1 ? "check" : "checks"}
            </span>
            <span>{last ? dayLabel(last) : ""}</span>
          </div>
        </div>
      ) : (
        <div className="mt-2 text-(--gray-9) text-[11px]">
          One check so far. The line draws from the second one.
        </div>
      )}
      <button
        type="button"
        className="mt-2 cursor-pointer border-0 bg-transparent p-0 text-(--gray-10) text-[11px] hover:text-(--gray-12)"
        onClick={() => setShowSql((open) => !open)}
      >
        {showSql ? "Hide SQL" : "Show SQL"}
      </button>
      {showSql ? (
        <div className="mt-1 max-h-28 overflow-hidden whitespace-pre-wrap break-words font-mono text-[11px] leading-[1.5]">
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
  const expandable = !!entry.body && entry.body.trim() !== entry.title.trim();
  return (
    <li className="doc-timeline-row" data-kind={entry.kind}>
      <span className="doc-timeline-dot" />
      <div className="min-w-0">
        <div className="flex items-baseline gap-2 text-(--gray-9) text-[11px]">
          <span className="doc-timeline-kind">{KIND_LABEL[entry.kind]}</span>
          {entry.who ? <span>{entry.who}</span> : null}
          <span className="ml-auto shrink-0 tabular-nums">
            {timeLabel(entry.at)}
          </span>
        </div>
        <div className="mt-0.5 text-(--gray-12) text-[12.5px] leading-snug">
          {open && entry.body ? (
            <span className="whitespace-pre-wrap break-words">
              {entry.body.replace(/\*\*/g, "")}
            </span>
          ) : (
            entry.title
          )}
          {expandable ? (
            <button
              type="button"
              className="ml-1.5 cursor-pointer text-(--gray-10) text-[11px] hover:text-(--gray-12)"
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
 * The whole of a watch, in one place with room to read: the numbers as charts,
 * what would decide the claim, what the scout follows, and everything that
 * happened, newest first. The thread stays a conversation; this is the record.
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
  const watch = thread.watch;
  const entries = useMemo(
    () => watchTimeline(thread, personName).reverse(),
    [thread],
  );
  if (!watch) return null;
  const brief = watch.brief;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="wide" className="doc-dossier">
        <DialogHeader>
          <div className="flex items-start gap-3 pr-8">
            <div className="min-w-0 flex-1">
              <DialogTitle className="doc-dossier-title">
                “{thread.anchor_text || "a section"}”
              </DialogTitle>
              <DialogDescription className="mt-1 flex items-center gap-2">
                <VerdictPill watch={watch} />
                <span className="min-w-0 truncate">
                  {watch.verdict.reason ||
                    (watch.status === "active"
                      ? `Watched since ${dayLabel(thread.created_at)}`
                      : "No longer watched")}
                </span>
                {watch.status === "active" && watch.next_check_at ? (
                  <span className="shrink-0 text-(--gray-9)">
                    · next check {timeLabel(watch.next_check_at)}
                  </span>
                ) : null}
              </DialogDescription>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <WatchHeaderActions
                watch={watch}
                onAction={onAction}
                pendingAction={pendingAction}
              />
            </div>
          </div>
        </DialogHeader>

        <DialogBody>
          <div className="doc-dossier-body">
            <div className="doc-dossier-column">
              {brief && brief.evidence.length > 0 ? (
                <section>
                  <h4 className="doc-dossier-heading">Stands on</h4>
                  <div className="flex flex-col gap-2.5">
                    {brief.evidence.map((evidence) => (
                      <EvidenceChart
                        key={`${evidence.label}:${evidence.query}`}
                        evidence={evidence}
                      />
                    ))}
                  </div>
                </section>
              ) : (
                <section>
                  <h4 className="doc-dossier-heading">Stands on</h4>
                  <p className="text-(--gray-10) text-[12.5px]">
                    {brief
                      ? "No numbers to recheck. The scout follows the signals."
                      : "The agent is turning the claim into checks."}
                  </p>
                </section>
              )}
              {brief && (brief.confirms || brief.refutes) ? (
                <section className="doc-dossier-rules">
                  {brief.confirms ? (
                    <div>
                      <h4 className="doc-dossier-heading">Confirmed when</h4>
                      <p>{brief.confirms}</p>
                    </div>
                  ) : null}
                  {brief.refutes ? (
                    <div>
                      <h4 className="doc-dossier-heading">Refuted when</h4>
                      <p>{brief.refutes}</p>
                    </div>
                  ) : null}
                </section>
              ) : null}
              {brief && brief.signals.length > 0 ? (
                <section>
                  <h4 className="doc-dossier-heading">
                    The scout follows
                    <span className="ml-1.5 font-normal text-(--gray-9) normal-case tracking-normal">
                      {watch.scout
                        ? "· daily"
                        : watch.scout_error
                          ? `· ${watch.scout_error}`
                          : "· starting"}
                    </span>
                  </h4>
                  <ul className="doc-watch-signals">
                    {brief.signals.map((signal) => (
                      <li key={signal}>{signal}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>

            <div className="doc-dossier-column">
              <h4 className="doc-dossier-heading">History</h4>
              <ul className="doc-timeline">
                {entries.map((entry) => (
                  <TimelineRow key={entry.id} entry={entry} />
                ))}
              </ul>
            </div>
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
