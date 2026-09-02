import {
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  DotsThreeIcon,
  EyeIcon,
  EyeSlashIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Spinner,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { DocMarkState } from "@posthog/ui/primitives/DocMark";
import { useState } from "react";
import { Spark } from "../extensions/DataValue";

type Watch = DocSchemas.DocWatch;
export type Decision = "confirmed" | "refuted";

const VERDICT_LABEL: Record<DocSchemas.WatchVerdictState, string> = {
  pending: "Compiling",
  holding: "Holding",
  moved: "Moved",
  confirmed: "Confirmed",
  refuted: "Refuted",
  stale: "Could not check",
};

const STOP_LABEL: Record<DocSchemas.WatchStopReason, string> = {
  section_removed: "the words left the page",
  page_done: "the page is done",
  page_deleted: "the page was deleted",
  handled: "it was marked handled",
  person: "someone stopped it",
  verdict: "it was decided",
};

/** The pill's word: the verdict while the watch runs, else why it does not. */
export function verdictLabel(watch: Watch): string {
  if (watch.status === "paused") return "Paused";
  if (watch.status === "stopped") {
    return watch.stopped_reason === "verdict"
      ? VERDICT_LABEL[watch.verdict.verdict]
      : "Stopped";
  }
  return VERDICT_LABEL[watch.verdict.verdict];
}

/** The mark's state for a watched claim, read off the watch alone. */
export function watchMarkState(watch: Watch): DocMarkState {
  if (watch.status !== "active") return "handled";
  if (watch.verdict.verdict === "moved") return "moved";
  if (watch.verdict.verdict === "stale") return "stale";
  return "still";
}

/** What the anchor in the text carries, for the colour of its eye. */
export function watchAnchorState(watch: Watch): string {
  if (watch.status !== "active") return "off";
  return watch.verdict.verdict;
}

export function VerdictPill({
  watch,
  className,
}: {
  watch: Watch;
  className?: string;
}) {
  return (
    <span
      className={className ? `doc-verdict ${className}` : "doc-verdict"}
      data-verdict={watch.verdict.verdict}
      data-status={watch.status}
    >
      {verdictLabel(watch)}
    </span>
  );
}

function formatNumber(value: number | null): string {
  if (value === null) return "—";
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** The change since the baseline, short enough for a figure. */
function deltaShort(evidence: DocSchemas.WatchEvidence): string {
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

/** One short line after the pill: when it was checked, and what follows it. */
export function statusLine(watch: Watch): string {
  if (watch.status === "stopped") {
    const why = watch.stopped_reason ? STOP_LABEL[watch.stopped_reason] : null;
    return why ? `Stopped, ${why}.` : "Stopped.";
  }
  if (watch.status === "paused") return "Paused while the page is done.";
  if (!watch.brief) return "The agent is turning the claim into checks.";
  const parts = [];
  if (watch.checked_at) {
    const when = formatRelativeTimeShort(watch.checked_at);
    parts.push(when === "now" ? "checked just now" : `checked ${when} ago`);
  }
  if (!watch.evidence_only) {
    parts.push(
      watch.scout
        ? "scout on it daily"
        : watch.scout_error
          ? "no scout"
          : "scout starting",
    );
  }
  return parts.join(" · ");
}

/**
 * Fixed under the quote, two lines at most: where the claim stands, then its
 * numbers as small figures. The rest is a click away in the dossier, so the
 * conversation keeps the column.
 */
export function WatchStrip({
  watch,
  onHistory,
}: {
  watch: Watch;
  onHistory: () => void;
}) {
  const evidence = watch.brief?.evidence ?? [];
  return (
    <div className="doc-watch-strip">
      <div className="doc-watch-status">
        <VerdictPill watch={watch} />
        <span
          className="doc-watch-status-text"
          title={watch.verdict.reason || statusLine(watch)}
        >
          {watch.verdict.reason || statusLine(watch)}
        </span>
        <button type="button" className="doc-watch-history" onClick={onHistory}>
          <ClockCounterClockwiseIcon size={13} />
          History
        </button>
      </div>
      {evidence.length > 0 ? (
        <div className="doc-watch-figures">
          {evidence.slice(0, 3).map((entry) => {
            const points = entry.history
              .map((point) => point[1])
              .filter((value): value is number => typeof value === "number");
            return (
              <span
                key={`${entry.label}:${entry.query}`}
                className="doc-watch-figure"
                data-moved={entry.moved}
                title={entry.label}
              >
                {points.length > 1 ? <Spark points={points} /> : null}
                <b>{formatNumber(entry.value)}</b>
                <span>{deltaShort(entry)}</span>
              </span>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Ask for the one line behind a decision, then close the watch with it. */
export function DecideDialog({
  decision,
  onClose,
  onDecide,
  isPending,
}: {
  decision: Decision | null;
  onClose: () => void;
  onDecide: (decision: Decision, reason: string) => void;
  isPending: boolean;
}) {
  const [reason, setReason] = useState("");
  const confirmed = decision === "confirmed";
  const decide = () => {
    if (!decision || !reason.trim()) return;
    onDecide(decision, reason.trim());
    setReason("");
  };
  return (
    <Dialog
      open={decision !== null}
      onOpenChange={(open) => {
        if (!open) {
          setReason("");
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {confirmed ? "Close as confirmed" : "Close as refuted"}
          </DialogTitle>
          <DialogDescription>
            {confirmed
              ? "The claim holds. The watch ends and the thread keeps your reason."
              : "The claim does not hold. The watch ends and the thread keeps your reason."}
          </DialogDescription>
        </DialogHeader>
        <Textarea
          autoFocus
          rows={2}
          placeholder="Why, in one line"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              decide();
            }
          }}
        />
        <DialogFooter>
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={isPending || !reason.trim()}
            onClick={decide}
          >
            {confirmed ? "Confirm" : "Refute"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The two controls of a watch: check now, and a menu with the rest. The menu
 * keeps stop, resume, and the two decisions off the column.
 */
export function WatchHeaderActions({
  watch,
  onAction,
  pendingAction,
}: {
  watch: Watch;
  onAction: (body: DocSchemas.WatchActionBody) => void;
  pendingAction: DocSchemas.WatchActionKind | null;
}) {
  const [deciding, setDeciding] = useState<Decision | null>(null);
  const active = watch.status === "active";
  const decided =
    watch.status === "stopped" && watch.stopped_reason === "verdict";
  const busy = pendingAction !== null && pendingAction !== "arm";
  return (
    <>
      {active && watch.brief && watch.brief.evidence.length > 0 ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Check now"
                disabled={busy}
                onClick={() => onAction({ action: "check" })}
              />
            }
          >
            {pendingAction === "check" ? (
              <Spinner className="size-3.5" />
            ) : (
              <ArrowsClockwiseIcon size={15} />
            )}
          </TooltipTrigger>
          <TooltipContent>Check the numbers now</TooltipContent>
        </Tooltip>
      ) : null}
      {decided ? null : (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Watch actions"
                disabled={busy}
              />
            }
          >
            <DotsThreeIcon size={16} weight="bold" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              onClick={() => onAction({ action: active ? "stop" : "resume" })}
            >
              {active ? <EyeSlashIcon size={14} /> : <EyeIcon size={14} />}
              {active ? "Stop watching" : "Watch again"}
            </DropdownMenuItem>
            {active && watch.brief ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => setDeciding("confirmed")}>
                  <CheckCircleIcon size={14} />
                  Close as confirmed…
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setDeciding("refuted")}>
                  <XCircleIcon size={14} />
                  Close as refuted…
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
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
