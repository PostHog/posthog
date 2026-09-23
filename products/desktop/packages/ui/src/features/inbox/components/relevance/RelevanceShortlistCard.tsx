import { recommendationPresentation } from "@posthog/core/inbox/relevance";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { Link } from "@tanstack/react-router";

export function RelevanceShortlistCard({
  report,
  saving,
  onSnooze,
}: {
  report: SignalReport;
  saving: boolean;
  onSnooze: () => void;
}) {
  const { action, reason } = recommendationPresentation(report);
  return (
    <article className="space-y-3 rounded border border-gray-6 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="min-w-0 flex-1 break-words font-medium">
          {report.title || "Untitled report"}
        </h3>
        <SignalReportPriorityBadge priority={report.priority} />
      </div>
      {deriveHeadline(report.summary) && (
        <p className="line-clamp-2 text-sm">{deriveHeadline(report.summary)}</p>
      )}
      <p className="text-gray-11 text-sm">{`You are a suggested reviewer. ${reason}`}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          nativeButton={false}
          render={
            <Link
              to="/reports/$reportId"
              params={{ reportId: report.id }}
              search={{ from: "/inbox" }}
            />
          }
          data-attr="inbox-shortlist-open"
        >
          {action}
        </Button>
        <Button
          variant="outline"
          disabled={saving}
          onClick={onSnooze}
          title="Hide only from your shortlist for seven days"
          data-attr="inbox-shortlist-not-now"
        >
          Not now
        </Button>
      </div>
    </article>
  );
}
