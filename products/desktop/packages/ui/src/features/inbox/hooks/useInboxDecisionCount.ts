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

const EMPTY_FILTER_ARRAY: never[] = [];

/**
 * The navigation badge needs only the ready-report count. Keeping it separate
 * from `useInboxSectionCounts` avoids polling the other two section counts on
 * every route.
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
  const prFilter = useInboxSignalsFilterStore((state) =>
    ignoreFilters ? "all" : state.prFilter,
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
  const query = useInboxReports(
    {
      status: "ready",
      has_implementation_pr:
        prFilter === "with_pr"
          ? true
          : prFilter === "without_pr"
            ? false
            : undefined,
      source_product:
        sourceProductFilter.length > 0
          ? sourceProductFilter.join(",")
          : undefined,
      priority: buildPriorityFilterParam(priorityFilter),
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
      limit: 1,
    },
    {
      enabled: enabled && scopeReady,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    },
  );

  return enabled ? (query.data?.count ?? 0) : 0;
}
