import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import {
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildSuggestedReviewerFilterParam,
  INBOX_REPORTS_TAB_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { INBOX_SCOPE_FOR_YOU } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";

const INBOX_ACTIVITY_PREVIEW_LIMIT = 3;
const INBOX_ACTIVITY_REFETCH_INTERVAL_MS = 60_000;
const EMPTY_REPORTS: SignalReport[] = [];

interface InboxActivityPreview {
  reports: SignalReport[];
  totalCount: number;
  isLoading: boolean;
  isIncluded: boolean;
}

export function useInboxActivityPreview(): InboxActivityPreview {
  const reportsInboxEnabled = useReportsInboxEnabled();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const inboxEnabled = useActivityFilterStore((state) =>
    authIdentity
      ? (state.inboxEnabledByAuthIdentity[authIdentity] ?? false)
      : false,
  );
  const inboxScope = useActivityFilterStore((state) => state.inboxScope);
  const sourceProductFilter = useActivityFilterStore(
    (state) => state.inboxSourceProductFilter,
  );
  const prFilter = useActivityFilterStore((state) => state.inboxPrFilter);
  const sortField = useActivityFilterStore((state) => state.inboxSortField);
  const sortDirection = useActivityFilterStore(
    (state) => state.inboxSortDirection,
  );
  const priorityFilter = useActivityFilterStore(
    (state) => state.inboxPriorityFilter,
  );
  const isIncluded = reportsInboxEnabled && inboxEnabled;
  const needsReviewer = isIncluded && inboxScope === INBOX_SCOPE_FOR_YOU;
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser, isLoading: isReviewerLoading } = useCurrentUser({
    client,
    enabled: needsReviewer,
  });
  const reviewerUuid =
    inboxScope === INBOX_SCOPE_FOR_YOU ? currentUser?.uuid : undefined;
  const scopeReady = !needsReviewer || reviewerUuid !== undefined;

  const query = useInboxReports(
    {
      status: INBOX_REPORTS_TAB_STATUS_FILTER,
      has_implementation_pr:
        prFilter === "with_pr"
          ? true
          : prFilter === "without_pr"
            ? false
            : undefined,
      ordering: buildSignalReportListOrdering(sortField, sortDirection),
      source_product:
        sourceProductFilter.length > 0
          ? sourceProductFilter.join(",")
          : undefined,
      priority: buildPriorityFilterParam(priorityFilter),
      suggested_reviewers: reviewerUuid
        ? buildSuggestedReviewerFilterParam([reviewerUuid])
        : undefined,
      limit: INBOX_ACTIVITY_PREVIEW_LIMIT,
    },
    {
      enabled: isIncluded && scopeReady,
      refetchInterval: INBOX_ACTIVITY_REFETCH_INTERVAL_MS,
      refetchIntervalInBackground: false,
    },
  );

  if (!isIncluded) {
    return {
      reports: EMPTY_REPORTS,
      totalCount: 0,
      isLoading: false,
      isIncluded: false,
    };
  }

  return {
    reports: query.data?.results ?? EMPTY_REPORTS,
    totalCount: query.data?.count ?? 0,
    isLoading:
      query.isLoading ||
      isReviewerLoading ||
      (needsReviewer && reviewerUuid === undefined),
    isIncluded: true,
  };
}
