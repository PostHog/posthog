import {
  buildPriorityFilterParam,
  buildSuggestedReviewerFilterParam,
} from "@posthog/core/inbox/reportFiltering";
import {
  INBOX_SCOPE_FOR_YOU,
  parseTeammateInboxScope,
} from "@posthog/core/inbox/reportMembership";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

/** The live statuses that aren't `ready`: what the Monitoring section holds. */
const MONITORING_STATUS_FILTER = "pending_input,failed,in_progress,candidate";

export interface InboxSectionCounts {
  /** Ready reports — the "Needs a decision" section's true total. */
  decision: number;
  /** The subset of ready reports carrying an implementation PR. */
  decisionPr: number;
  /** Everything else live: running, queued, waiting on input, failed. */
  monitoring: number;
  isLoading: boolean;
}

/**
 * Server-side counts for the inbox's sections and badges.
 *
 * At this dataset's real size (tens of thousands of live reports in a shared
 * project) any count derived from loaded pages is a count of a window, not of
 * reality — which is where every badge/section mismatch came from. So each
 * number here is a `limit: 1` count query on the dimensions the API can
 * actually filter server-side (status, PR presence, reviewer scope, source,
 * priority), and the sections are deliberately defined on those dimensions.
 *
 * Scope and the filter bar's source/priority choices are mirrored into every
 * query so the counts move with what the list shows. Search is not — it's a
 * client-side title match, so surfaces showing searched rows must count those
 * rows instead.
 */
export function useInboxSectionCounts(): InboxSectionCounts {
  const scope = useInboxReviewerScopeStore((s) => s.scope);
  const sourceProductFilter = useInboxSignalsFilterStore(
    (s) => s.sourceProductFilter,
  );
  const priorityFilter = useInboxSignalsFilterStore((s) => s.priorityFilter);
  const prFilter = useInboxSignalsFilterStore((s) => s.prFilter);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const isForYou = scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = parseTeammateInboxScope(scope);
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);

  const shared = {
    source_product:
      sourceProductFilter.length > 0
        ? sourceProductFilter.join(",")
        : undefined,
    priority: buildPriorityFilterParam(priorityFilter),
    // The decision-PR caption query overrides this with `true` via spread.
    has_implementation_pr:
      prFilter === "with_pr"
        ? true
        : prFilter === "without_pr"
          ? false
          : undefined,
    suggested_reviewers: reviewerUuid
      ? buildSuggestedReviewerFilterParam([reviewerUuid])
      : undefined,
    limit: 1,
  };
  const options = {
    // "For you" must carry the user's reviewer filter; hold until it resolves.
    enabled: !isForYou || reviewerUuid != null,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  };

  const decisionQuery = useInboxReports(
    { ...shared, status: "ready" },
    options,
  );
  const decisionPrQuery = useInboxReports(
    { ...shared, status: "ready", has_implementation_pr: true },
    options,
  );
  const monitoringQuery = useInboxReports(
    { ...shared, status: MONITORING_STATUS_FILTER },
    options,
  );

  return {
    decision: decisionQuery.data?.count ?? 0,
    decisionPr: decisionPrQuery.data?.count ?? 0,
    monitoring: monitoringQuery.data?.count ?? 0,
    isLoading:
      decisionQuery.isLoading ||
      monitoringQuery.isLoading ||
      (isForYou && reviewerUuid == null),
  };
}
