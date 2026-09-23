import { INBOX_SCOPE_ENTIRE_PROJECT } from "@posthog/core/inbox/reportMembership";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useSnoozeRecommendation } from "@posthog/ui/features/inbox/hooks/useSnoozeRecommendation";
import { useTrackShortlistImpressions } from "@posthog/ui/features/inbox/hooks/useTrackShortlistImpressions";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { type ReactNode, useState } from "react";
import { RelevanceShortlist } from "./RelevanceShortlist";

export function RelevancePilotContent({ children }: { children: ReactNode }) {
  const [showQueue, setShowQueue] = useState(false);
  const [lastSnoozed, setLastSnoozed] = useState<SignalReport | null>(null);
  const query = useInboxReports(
    { view: "for_you", limit: 5 },
    { enabled: !showQueue, refetchInterval: 60_000, staleTime: 0 },
  );
  const mutation = useSnoozeRecommendation();
  const setScope = useInboxReviewerScopeStore((state) => state.setScope);
  useTrackShortlistImpressions(
    showQueue || !query.isSuccess ? [] : query.data.results,
  );
  if (showQueue)
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <Button
          className="m-4 self-start"
          variant="outline"
          onClick={() => setShowQueue(false)}
        >
          Back to shortlist
        </Button>
        {children}
      </div>
    );
  return (
    <RelevanceShortlist
      reports={query.data?.results ?? []}
      loading={query.isPending}
      failed={query.isError}
      saving={mutation.isPending}
      lastSnoozed={lastSnoozed}
      onRetry={() => void query.refetch()}
      onShowQueue={() => {
        setScope(INBOX_SCOPE_ENTIRE_PROJECT);
        setShowQueue(true);
      }}
      onSnooze={(report, snoozed) =>
        mutation.mutate(
          { report, snoozed },
          { onSuccess: () => setLastSnoozed(snoozed ? report : null) },
        )
      }
    />
  );
}
