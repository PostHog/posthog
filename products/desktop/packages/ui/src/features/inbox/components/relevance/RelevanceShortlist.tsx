import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { RelevanceShortlistCard } from "./RelevanceShortlistCard";

export interface RelevanceShortlistProps {
  reports: SignalReport[];
  loading: boolean;
  failed: boolean;
  saving: boolean;
  lastSnoozed: SignalReport | null;
  onRetry: () => void;
  onShowQueue: () => void;
  onSnooze: (report: SignalReport, snoozed: boolean) => void;
}

export function RelevanceShortlist({
  reports,
  loading,
  failed,
  saving,
  lastSnoozed,
  onRetry,
  onShowQueue,
  onSnooze,
}: RelevanceShortlistProps) {
  return (
    <div
      className="mx-auto w-full max-w-3xl space-y-4 overflow-auto p-4"
      data-attr="inbox-relevance-shortlist"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-lg">For you</h2>
          <p className="text-gray-11 text-sm">
            Up to five reports that need attention.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={onShowQueue}
          data-attr="inbox-shortlist-wider-queue"
        >
          Browse all reports
        </Button>
      </div>
      <p className="text-gray-11 text-sm">
        Suggested to you, P0–P2, highest priority first. Reports already being
        handled stay in the wider queue.
      </p>
      {lastSnoozed && (
        <div
          className="flex flex-wrap items-center gap-2 rounded border border-gray-6 p-3"
          aria-live="polite"
        >
          <span>
            Hidden from your shortlist for seven days. Everyone else can still
            see it.
          </span>
          <Button
            variant="outline"
            disabled={saving}
            onClick={() => onSnooze(lastSnoozed, false)}
          >
            Undo
          </Button>
        </div>
      )}
      {failed ? (
        <div role="alert">
          <p>Could not load your shortlist.</p>
          <Button onClick={onRetry}>Try again</Button>
        </div>
      ) : loading ? (
        <p aria-live="polite">Loading your shortlist…</p>
      ) : reports.length ? (
        <div className="space-y-3">
          {reports.map((report) => (
            <RelevanceShortlistCard
              key={report.id}
              report={report}
              saving={saving}
              onSnooze={() => onSnooze(report, true)}
            />
          ))}
        </div>
      ) : (
        <p>
          Nothing needs your attention here right now. You can still browse all
          reports, including lower-priority and snoozed reports.
        </p>
      )}
    </div>
  );
}
