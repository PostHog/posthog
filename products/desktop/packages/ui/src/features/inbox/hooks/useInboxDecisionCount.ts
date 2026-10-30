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
import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

const EMPTY_FILTER_ARRAY: never[] = [];

/**
 * The navigation badge shows the ready-report count: the reports with and
 * without an implementation PR. With the same filters as the inbox list it
 * shares that list's count request.
 */
export function useInboxDecisionCount(options?: {
  enabled?: boolean;
  ignoreFilters?: boolean;
}): number {
  const enabled = options?.enabled ?? true;
  const ignoreFilters = options?.ignoreFilters ?? false;
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const sourceProductFilter = useInboxSignalsFilterStore((state) =>
    ignoreFilters ? EMPTY_FILTER_ARRAY : state.sourceProductFilter,
  );
  const priorityFilter = useInboxSignalsFilterStore((state) =>
    ignoreFilters ? EMPTY_FILTER_ARRAY : state.priorityFilter,
  );
  const isForYou = scope === INBOX_SCOPE_FOR_YOU;
  const teammateUuid = parseTeammateInboxScope(scope);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({
    client,
    enabled: enabled && isForYou && teammateUuid === null,
  });
  const reviewerUuid =
    teammateUuid ?? (isForYou ? (currentUser?.uuid ?? null) : null);
  const scopeReady = !isForYou || reviewerUuid !== null;
  const query = useInboxSectionCounts(
    {
      source_product:
        sourceProductFilter.length > 0
          ? sourceProductFilter.join(",")
          : undefined,
      priority: buildPriorityFilterParam(priorityFilter),
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
    },
    { enabled: enabled && scopeReady, refetchInterval: 60_000 },
  );

  const counts = query.data;
  return enabled && counts ? counts.pull_requests + counts.reports : 0;
}
